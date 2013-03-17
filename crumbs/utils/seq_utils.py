# Copyright 2012 Jose Blanca, Peio Ziarsolo, COMAV-Univ. Politecnica Valencia
# This file is part of seq_crumbs.
# seq_crumbs is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# seq_crumbs is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR  PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with seq_crumbs. If not, see <http://www.gnu.org/licenses/>.

import re
import itertools
from multiprocessing import Pool
from copy import deepcopy

from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

from crumbs.utils.tags import (UPPERCASE, LOWERCASE, SWAPCASE, SEQITEM,
                               SEQRECORD)
from crumbs.seqio import SeqWrapper

# pylint: disable=R0903
# pylint: disable=C0111


def replace_seq_same_length(seqrecord, seq_str):
    'It replaces the str with another of equal length keeping the annots.'
    annots = seqrecord.letter_annotations
    seqrecord.letter_annotations = {}
    alphabet = seqrecord.seq.alphabet
    seqrecord.seq = Seq(seq_str, alphabet)
    seqrecord.letter_annotations = annots
    return seqrecord


def _copy_seqrecord(seqrec, seq=None, name=None, id_=None):
    'Given a seqrecord it returns a new seqrecord with seq or qual changed.'
    if seq is None:
        seq = seqrec.seq
    if id_ is  None:
        id_ = seqrec.id
    if name is None:
        name = seqrec.name

    # the letter annotations
    let_annot = {annot: v for annot, v in seqrec.letter_annotations.items()}

    # the rest of parameters
    description = seqrec.description
    dbxrefs = seqrec.dbxrefs[:]
    features = seqrec.features[:]  # the features are not copied
    annotations = deepcopy(seqrec.annotations)

    # the new sequence
    new_seq = SeqRecord(seq=seq, id=id_, name=name, description=description,
                        dbxrefs=dbxrefs, features=features,
                        annotations=annotations, letter_annotations=let_annot)

    return new_seq


def uppercase_length(string):
    'It returns the number of uppercase characters found in the string'
    return len(re.findall("[A-Z]", string))


def get_uppercase_segments(string):
    '''It detects the unmasked regions of a sequence

    It returns a list of (start, end) tuples'''
    start = 0
    for is_upper, group in itertools.groupby(string, lambda x: x.isupper()):
        group = list(group)
        end = start + len(group) - 1
        if is_upper:
            yield start, end
        start = end + 1


class ChangeCase(object):
    'It changes the sequence case.'

    def __init__(self, action):
        'The initiator'
        if action not in (UPPERCASE, LOWERCASE, SWAPCASE):
            msg = 'Action should be: uppercase, lowercase or invertcase'
            raise ValueError(msg)
        self.action = action

    def __call__(self, seqrecords):
        'It changes the case of the seqrecords.'
        action = self.action
        processed_seqs = []
        for seqrecord in seqrecords:
            str_seq = str(seqrecord.seq)
            if action == UPPERCASE:
                str_seq = str_seq.upper()
            elif action == LOWERCASE:
                str_seq = str_seq.lower()
            elif action == SWAPCASE:
                str_seq = str_seq.swapcase()
            else:
                raise NotImplementedError()
            seqrecord = replace_seq_same_length(seqrecord, str_seq)
            processed_seqs.append(seqrecord)
        return processed_seqs


def append_to_description(seqrecord, text):
    'it appends the text to the seqrecord description'
    desc = get_description(seqrecord)
    if desc in (None, get_name(seqrecord), '<unknown description>'):
        desc = ''
    desc += text
    seqrecord.object.description = desc


class _FunctionRunner(object):
    'a class to join all the mapper functions in a single function'
    def __init__(self, map_functions):
        'Class initiator'
        self.map_functions = map_functions

    def __call__(self, seq_packet):
        'It runs all the map_functions for each seq_packet '
        processed_packet = seq_packet
        for map_function in self.map_functions:
            processed_packet = map_function(processed_packet)
        return processed_packet


def process_seq_packets(seq_packets, map_functions, processes=1,
                        keep_order=True):
    'It processes the SeqRecord packets'
    if processes > 1:
        workers = Pool(processes=processes)
        mapper = workers.imap if keep_order else workers.imap_unordered
    else:
        workers = None
        mapper = itertools.imap
    run_functions = _FunctionRunner(map_functions)

    seq_packets = mapper(run_functions, seq_packets)

    return seq_packets, workers


def get_title(seq):
    'Given a seq it returns the title'
    # TODO remove this check when everything is adapted to the new system
    if 'SeqRecord' in seq.__class__.__name__:
        seq_class = SEQRECORD
    else:
        seq_class = seq.kind
        seq = seq.object

    if seq_class == SEQITEM:
        title = seq.lines[0][1:]
    elif seq_class == SEQRECORD:
        title = seq.id + ' ' + seq.description
    else:
        msg = 'Do not know how to guess title form this seq class'
        raise NotImplementedError(msg)
    return title


def get_description(seq):
    seq_class = seq.kind
    seq = seq.object
    if seq_class == SEQITEM:
        title_items = seq.lines[0].split(' ', 1)
        desc = title_items[1] if len(title_items) == 2 else None
    elif seq_class == SEQRECORD:
        desc = seq.description
        if desc == '<unknown description>':  # BioPython default
            return None
    return desc


def get_name(seq):
    if 'SeqRecord' in seq.__class__.__name__:
        seq_class = SEQRECORD
    else:
        seq_class = seq.kind
        seq = seq.object
    if seq_class == SEQITEM:
        name = seq.name
    elif seq_class == SEQRECORD:
        name = seq.id
    return name


def get_file_format(seq):
    seq_class = seq.kind

    if seq_class == SEQITEM:
        fmt = seq.file_format
    elif seq_class == SEQRECORD:
        fmt = None
    return fmt


def _break():
    raise StopIteration


def _get_seqitem_str_lines(seq):
    fmt = seq.file_format
    sitem = seq.object
    if 'fastq' in fmt and not 'multiline' in fmt:
        lines = sitem.lines[1:2]
    else:
        lines = (_break() if l.startswith('+') else l for l in sitem.lines[1:])
    return lines


def get_str_seq(seq):
    seq_class = seq.kind
    if seq_class == SEQITEM:
        seq = ''.join((line.rstrip() for line in _get_seqitem_str_lines(seq)))
    elif seq_class == SEQRECORD:
        seq = str(seq.object.seq)
    return seq


def get_length(seq):
    seq_class = seq.kind
    if seq_class == SEQITEM:
        length = lambda l: len(l) - 1   # It assumes line break and no spaces
        length = sum(map(length, _get_seqitem_str_lines(seq)))
    elif seq_class == SEQRECORD:
        length = len(seq.object)
    return length


def get_qualities(seq):
    seq_class = seq.kind
    seq = seq.object
    if seq_class == SEQITEM:
        raise NotImplementedError('No qualities yet for SeqItem.')
    elif seq_class == SEQRECORD:
        annots = seq.letter_annotations['phred_quality']
    return annots


def get_annotations(seq):
    seq_class = seq.kind
    seq = seq.object
    if seq_class == SEQITEM:
        raise NotImplementedError('SeqItem has no annotation yet.')
    elif seq_class == SEQRECORD:
        annots = seq.annotations
    return annots


def copy_seq(seqwrapper, seq=None, name=None):
    seq_class = seqwrapper.kind
    seq_obj = seqwrapper.object
    if seq_class == SEQITEM:
        # It has to take into account that the seq is a string and it has
        # to be transformed in a list of lines, with the \n
        raise NotImplementedError('SeqItem has copy yet.')
    elif seq_class == SEQRECORD:
        seq_obj = _copy_seqrecord(seq_obj, seq=seq, name=name, id_=name)
        seq = SeqWrapper(kind=seqwrapper.kind, object=seq_obj,
                         file_format=seqwrapper.file_format)
    return seq


def slice_seq(seq, start, stop):
    seq_class = seq.kind
    if seq_class == SEQITEM:
        # The easiest way it to slice the seq string and the qualities list
        # If its a multiline fastq you can transform it in a single line fastq
        raise NotImplementedError('SeqItem has no slicing yet.')
    elif seq_class == SEQRECORD:
        seq_obj = seq.object[start:stop]
    return SeqWrapper(seq.kind, object=seq_obj, file_format=seq.file_format)
