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

import os.path
import shutil
from subprocess import PIPE
from tempfile import NamedTemporaryFile

from crumbs.utils.bin_utils import (check_process_finishes, get_binary_path,
                                    popen, get_num_threads)
from crumbs.settings import get_setting
from crumbs.utils.file_utils import TemporaryDir
import subprocess
import pysam
from crumbs.utils.file_formats import get_format
from crumbs.seq import SeqItem, SeqWrapper, get_str_seq, get_name
from crumbs.utils.tags import SEQITEM
from crumbs.exceptions import IncompatibleFormatError
from crumbs.iterutils import sorted_items
from crumbs.seqio import read_seqs


def _bwa_index_exists(index_path):
    'It checks if a a bwa index exists giving its path'
    return os.path.exists('{}.bwt'.format(index_path))


def _create_bwa_index(index_fpath):
    binary = get_binary_path('bwa')
    # how many sequences do we have?
    n_seqs = [l for l in open(index_fpath) if l[0] == '>']
    algorithm = 'bwtsw' if n_seqs > 10000 else 'is'
    cmd = [binary, 'index', '-a', algorithm, index_fpath]
    process = popen(cmd, stdout=PIPE, stderr=PIPE)
    check_process_finishes(process, binary=cmd[0])


def get_or_create_bwa_index(fpath, directory=None):
    'It creates the bwa index for the given reference'

    fpath = os.path.abspath(fpath)
    if directory is not None:
        index_fpath = os.path.join(directory, os.path.basename(fpath))
    else:
        index_fpath = fpath

    if not _bwa_index_exists(index_fpath):
        if os.path.exists(index_fpath):
            temp_dir = TemporaryDir()
            tmp_index_fpath = os.path.join(temp_dir.name,
                                           os.path.basename(index_fpath))
            os.symlink(fpath, tmp_index_fpath)
            _create_bwa_index(tmp_index_fpath)
            for file_ in os.listdir(temp_dir.name):
                if file_ == os.path.basename(index_fpath):
                    continue
                shutil.copy(os.path.join(temp_dir.name, file_),
                            os.path.join(os.path.dirname(index_fpath), file_))
        else:
            os.symlink(fpath, index_fpath)
            _create_bwa_index(index_fpath)

    return index_fpath


def map_with_bwamem(index_fpath, unpaired_fpath=None, paired_fpaths=None,
                   threads=None, log_fpath=None, extra_params=None):
    'It maps with bwa ws algorithm'
    if paired_fpaths is None and unpaired_fpath is None:
        raise RuntimeError('At least one file to map is required')
    elif paired_fpaths is not None and unpaired_fpath is not None:
        msg = 'Bwa can not map unpaired and unpaired reads together'
        raise RuntimeError(msg)

    if extra_params is None:
        extra_params = []

    binary = get_binary_path('bwa')
    cmd = [binary, 'mem', '-t', str(get_num_threads(threads)), index_fpath]
    cmd.extend(extra_params)

    if paired_fpaths is not None:
        cmd.extend(paired_fpaths)
    if unpaired_fpath is not None:
        cmd.append(unpaired_fpath)

    if log_fpath is None:
        stderr = NamedTemporaryFile(suffix='.stderr')
    else:
        stderr = open(log_fpath, 'w')
    #raw_input(' '.join(cmd))
    bwa = popen(cmd, stderr=stderr, stdout=PIPE)
    return bwa


def _bowtie2_index_exists(index_path):
    'It checks if a a bowtie2 index exists giving its path'
    return os.path.exists('{}.1.bt2'.format(index_path))


def get_or_create_bowtie2_index(fpath, directory=None):
    "it creates the bowtie2 index"
    binary = get_binary_path('bowtie2-build')
    if directory is not None:
        index_fpath = os.path.join(directory, os.path.basename(fpath))
    else:
        index_fpath = fpath
    if not _bowtie2_index_exists(index_fpath):
        cmd = [binary, '-f', fpath, index_fpath]
        process = popen(cmd, stdout=PIPE, stderr=PIPE)
        check_process_finishes(process, binary=cmd[0])
    return index_fpath


def map_with_bowtie2(index_fpath, paired_fpaths=None,
                     unpaired_fpaths=None, readgroup=None, threads=None,
                     log_fpath=None, preset='very-sensitive-local',
                     extra_params=None):
    '''It maps with bowtie2.

    paired_seqs is a list of tuples, in which each tuple are paired seqs
    unpaired_seqs is a list of files
    '''
    if readgroup is None:
        readgroup = {}

    if extra_params is None:
        extra_params = []

    if paired_fpaths is None and unpaired_fpaths is None:
        raise RuntimeError('At least one file to map is required')

    binary = get_binary_path('bowtie2')
    cmd = [binary, '-x', index_fpath, '--{0}'.format(preset),
           '-p', str(get_num_threads(threads))]

    cmd.extend(extra_params)
    if unpaired_fpaths:
        cmd.extend(['-U', ','.join(unpaired_fpaths)])
    if paired_fpaths:
        plus = [pairs for pairs in paired_fpaths[0]]
        minus = [pairs for pairs in paired_fpaths[1]]
        cmd.extend(['-1', ','.join(plus), '-2', ','.join(minus)])

    if 'ID' in readgroup.keys():
        for key, value in readgroup.items():
            if key not in ('ID', 'LB', 'SM', 'PL'):
                msg = 'The readgroup header tag is not valid: {}'.format(key)
                raise RuntimeError(msg)
            if key == 'ID':
                cmd.extend(['--rg-id', value])
            else:
                cmd.extend(['--rg', '{0}:{1}'.format(key, value)])

    if log_fpath is None:
        stderr = NamedTemporaryFile(suffix='.stderr')
    else:
        stderr = open(log_fpath, 'w')

#    raw_input(' '.join(cmd))
    bowtie2 = popen(cmd, stderr=stderr, stdout=PIPE)
    # print bowtie2.stdout.read()
    return bowtie2


def map_process_to_bam(map_process, bam_fpath, log_fpath=None):
    if log_fpath is None:
        stderr = NamedTemporaryFile(suffix='.stderr')
    else:
        stderr = open(log_fpath, 'w')

    cmd = [get_binary_path('samtools'), 'view', '-h', '-b', '-S', '-', '-o',
           bam_fpath]

    samtools = popen(cmd, stdin=map_process.stdout, stderr=stderr)
    map_process.stdout.close()  # Allow p1 to receive a SIGPIPE if samtools exits.
    samtools.communicate()


def sort_mapped_reads(map_process, out_fpath, key='coordinate',
                      tempdir='/tmp'):
    picard_tools = get_setting("PICARD_TOOLS_DIR")
    fpath = os.path.join(picard_tools, 'SortSam.jar')
    cmd = ['java', '-jar', fpath, 'I=/dev/stdin',
           'O=' + out_fpath, 'SO=' + key, 'TMP_DIR=' + tempdir,
           'VALIDATION_STRINGENCY=LENIENT']
    sort = subprocess.Popen(cmd, stdin=map_process.stdout, stderr=PIPE)
    stderr = sort.stderr
    sort.wait()
    if sort.returncode:
        msg = 'Something happened running picard sort:\n'
        msg += stderr.read()
        raise RuntimeError(msg)
    assert sort.returncode == 0


def alignedread_to_seqitem(aligned_read, file_format):
    name = aligned_read.qname
    seq = aligned_read.seq + '\n'
    quality = aligned_read.qual
    if 'fasta' in file_format:
        lines = ['>' + name + '\n', seq]
    elif 'fastq' in file_format:
        lines = ['@' + name + '\n', seq, '+\n', quality + '\n']
    else:
        raise IncompatibleFormatError('Not supported format: ' + file_format)
    return SeqWrapper(SEQITEM, SeqItem(name, lines), file_format)


def sort_by_position_in_ref(in_fhands, ref_fpath, directory=None,
                            tempdir=None):
    in_fpaths = [fhand.name for fhand in in_fhands]
    file_format = get_format(in_fhands[0])
    extra_params = ['-f'] if 'fasta' in file_format else []
    index_fpath = get_or_create_bowtie2_index(ref_fpath, directory)
    bowtie2 = map_with_bowtie2(index_fpath, unpaired_fpaths=in_fpaths,
                               extra_params=extra_params)
    out_fhand = NamedTemporaryFile()
    sort_mapped_reads(bowtie2, out_fhand.name, tempdir=tempdir)
    samfile = pysam.Samfile(out_fhand.name)
    for aligned_read in samfile:
        yield alignedread_to_seqitem(aligned_read, file_format)


def sort_fastx_files(in_fhands, key, ref_fpath=None, directory=None,
                     max_items_in_memory=None, tempdir='/tmp'):
    if key == 'seq':
        reads = read_seqs(in_fhands)
        return sorted_items(reads, key=get_str_seq, tempdir=tempdir,
                            max_items_in_memory=max_items_in_memory)
    elif key == 'coordinate':
        return sort_by_position_in_ref(in_fhands, ref_fpath,
                                       directory=directory,
                                       tempdir=tempdir)
    elif key == 'name':
        reads = read_seqs(in_fhands)
        return sorted_items(reads, key=get_name, tempdir=tempdir,
                            max_items_in_memory=max_items_in_memory)
    else:
        raise ValueError('Non-supported sorting key')
