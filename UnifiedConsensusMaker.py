#!/usr/bin/env python3

"""UnifiedConsensusMaker.py
Version 3.1
May 29, 2019
Programs by Scott Kennedy(1)
V3.1 Update by Brendan Kohrn(1)
(1) Department of Pathology, University of Washington School of Medicine, Seattle, WA 98195
  
Changelog:
V3.1: Add loclen option to accommodate dumis, fix last-read skip issue, 
      and update to python3.  Also, add docstring to program

This program is intended to convert raw sequencing reads from Duplex 
Sequencing libraries into SSCS and DCS sequences for later analysis.  
It has three parts: first, move barcode sequences to the read name, 
second, sort based on read names, and third, make consensuses based on 
those barcode sequences.  

Settings considerations:
--input is a paired-end, unaligned bam file, such as from PicardTools 
    FastqToSam
--taglen, --spacerlen, and --loclen should be set based on the library 
    preperation protocol used.  
        If dumis are being used, --loclen must 
    be >0.  
        For the method in Nature Protocols, --taglen is 12, 
    --spacerlen is 5, and --loclen can be 0.  

After this, further steps might include:
    Aligning (with BWA, etc)
    Read trimming (fixed-length trimming and/or overlap trimming)
    Local realignment (such as with IndelRealigner from GATK 3.8)
    Variant calling

When doing variant calling, remember that, for Duplex Sequencing, 
    samples should not be considered diploid
"""

import sys
import os
import pysam
import gzip
from argparse import ArgumentParser
from collections import defaultdict

class iteratorWrapper:
    def __init__(self, inIterator, finalValue):
        self.it = inIterator
        self.finalValue = finalValue
        self.endIter = False
    def __iter__(self):
        return(self)
    def __next__(self):
        try:
            temp = next(self.it)
        except StopIteration:
            if self.endIter == False:
                temp = self.finalValue
                self.endIter = True
            else:
                raise(StopIteration)
        return(temp)
    next = __next__

def consensus_caller(input_reads, cutoff, tag, length_check):

    nuc_identity_list = [0, 0, 0, 0, 0, 0]  
    # In the order of T, C, G, A, N, Total
    nuc_key_dict = {0: 'T', 1: 'C', 2: 'G', 3: 'A', 4: 'N'}
    consensus_seq = ''

    if length_check is True:

        for read in input_reads[1:]:
            if len(read) != len(input_reads[0]):
                raise Exception((f"Read lengths for tag {tag} used for "
                                 f"calculating the SSCS are not uniform!!!"
                                 ))

    for i in range(len(input_reads[0])):  
        # Count the types of nucleotides at a position in a read.
        # i is the nucleotide index within a read in groupedReadsList
        for j in range(len(input_reads)):  
        # Do this for every read that comprises a tag family.
        # j is the read index within groupedReadsList
            try:
                if input_reads[j][i] == 'T':
                    nuc_identity_list[0] += 1
                elif input_reads[j][i] == 'C':
                    nuc_identity_list[1] += 1
                elif input_reads[j][i] == 'G':
                    nuc_identity_list[2] += 1
                elif input_reads[j][i] == 'A':
                    nuc_identity_list[3] += 1
                elif input_reads[j][i] == 'N':
                    nuc_identity_list[4] += 1
                else:
                    nuc_identity_list[4] += 1
                nuc_identity_list[5] += 1
            except Exception:
                break
        try:
            for j in [0, 1, 2, 3, 4]:
                if (float(nuc_identity_list[j])
                        /float(nuc_identity_list[5])
                        ) >= cutoff:
                    consensus_seq += nuc_key_dict[j]
                    break
                elif j == 4:
                    consensus_seq += 'N'
        except:
            consensus_seq += 'N'
        nuc_identity_list = [0, 0, 0, 0, 0, 0]  
        # Reset for the next nucleotide position

    return consensus_seq


def qual_calc(qual_list):
    return [sum(qual_score) for qual_score in zip(*qual_list)]

def main():
    parser = ArgumentParser()
    parser.add_argument(
        '--input', 
        dest = 'in_bam', 
        required = True,
        help = 'Path to unaligned, paired-end, bam file.'
        )
    parser.add_argument(
        '--taglen', 
        dest = 'tag_len', 
        type = int, 
        default = 12,
        help = 'Length in bases of the duplex tag sequence.[12]'
        )
    parser.add_argument(
        '--spacerlen', 
        dest = 'spcr_len', 
        type = int, 
        default = 5,
        help = (f'Length in bases of the spacer sequence between'
                f'duplex tag and the start of target DNA. [5]'
                )
        )
    parser.add_argument(
        "--loclen", 
        dest = 'loc_len', 
        type = int, 
        default = 0, 
        action = "store",
        help = (f"Number of base pairs to add to barcode for location "
                f"specificity.  Bases are not removed from read.  [0]"
                )
        )
    parser.add_argument(
        "--tagstats", 
        dest = 'tagstats', 
        action = "store_true",
        help = "Output tagstats file"
        )
    parser.add_argument(
        '--minmem', 
        dest = 'minmem', 
        type = int, 
        default = 3,
        help = "Minimum number of reads allowed to comprise a consensus. [3]"
        )
    parser.add_argument(
        '--maxmem', 
        dest = 'maxmem', 
        type = int, 
        default = 200,
        help = "Maximum number of reads allowed to comprise a consensus. [200]"
                        )
    parser.add_argument(
        '--cutoff', 
        dest = 'cutoff', 
        type = float, 
        default = .7,
        help = (f"Percentage of nucleotides at a given position "
                f"in a read that must be identical in order "
                f"for a consensus to be called at that position. "
                f"[0.7]"
                )
        )
    parser.add_argument(
        '--Ncutoff', 
        dest = 'Ncutoff', 
        type = float, 
        default = 1,
        help = (f"With --filt 'n', maximum fraction of Ns allowed in a "
                f"consensus [1.0]"
                )
        )
    parser.add_argument(
        '--write-sscs', 
        dest = 'write_sscs', 
        action = "store_true",
        help = "Print the SSCS reads to file in FASTQ format"
        )
    parser.add_argument(
        '--without-dcs', 
        dest = 'without_dcs', 
        action = "store_true",
        help = "Don't print final DCS reads"
        )
    parser.add_argument(
        "--rep_filt", 
        action = "store",  
        type = int, 
        dest = 'rep_filt',
        default = 9,
        help = (f"Remove tags with homomeric runs of nucleotides of length "
                f"x. [9]"
                )
        )
    parser.add_argument(
        '--prefix', 
        dest = 'prefix', 
        type = str, 
        required = True,
        help = "Sample name to uniquely identify samples"
        )
    o = parser.parse_args()

    dummy_header = {'HD': {'VN': '1.0'}, 
                    'SQ': [{'LN': 1575, 'SN': 'chr1'}, 
                           {'LN': 1584, 'SN': 'chr2'}
                           ]
                    }
    in_bam_file = pysam.AlignmentFile(o.in_bam, "rb", check_sq=False)
    temp_bam = pysam.AlignmentFile(f"{o.prefix}.temp.bam", 
                                   'wb', 
                                   header=dummy_header
                                   )
    paired_end_count = 1

    if o.write_sscs is True:

        read1_sscs_fq_file = gzip.open(f"{o.prefix}_read1_sscs.fq.gz", 'wt')
        read2_sscs_fq_file = gzip.open(f"{o.prefix}_read2_sscs.fq.gz", 'wt')

    if o.without_dcs is False:
        read1_dcs_fq_file = gzip.open(f"{o.prefix}_read1_dcs.fq.gz", 'wt')
        read2_dcs_fq_file = gzip.open(f"{o.prefix}_read2_dcs.fq.gz", 'wt')

    '''This block of code takes an unaligned bam file, extracts the tag 
    sequences from the reads, and converts them to to "ab/ba" format 
    where 'a' and 'b' are the tag sequences from Read 1 and Read 2, 
    respectively. Conversion occurs by putting the tag with the "lesser" 
    value in front of the tag with the "higher" value. The original 
    tag orientation is denoted by appending #ab or #ba to the end of 
    the tag. After conversion, the resulting temporary bam file is then
    sorted by read name.
    '''
    tl = o.tag_len
    sl = o.spcr_len
    ll = o.loc_len
    print("Parsing tags...")

    for line in in_bam_file.fetch(until_eof=True):

        if paired_end_count % 2 == 1:

            temp_read1_entry = pysam.AlignedSegment()
            temp_read1_entry.query_name = line.query_name
            temp_read1_entry.query_sequence = line.query_alignment_sequence
            temp_read1_entry.query_qualities = line.query_alignment_qualities

        if paired_end_count % 2 == 0:

            temp_bam_entry = pysam.AlignedSegment()
            
            tag1 = (
                f"{temp_read1_entry.query_sequence[: tl]}"
                f"{temp_read1_entry.query_sequence[tl + sl : tl + sl + ll]}"
                )
            tag2 = (
                f"{line.query_sequence[: tl]}"
                f"{line.query_sequence[tl + sl : tl + sl + ll]}"
                )
            
            if tag1 > tag2:
                temp_bam_entry.query_name = tag1 + tag2 + '#ab'

            elif tag1 < tag2:
                temp_bam_entry.query_name = tag2 + tag1 + '#ba'

            elif tag1 == tag2:
                paired_end_count += 1
                continue

            # Write entries for Read 1
            temp_bam_entry.query_name += ":1"
            temp_bam_entry.query_sequence = (
                f"{temp_read1_entry.query_sequence[o.tag_len + o.spcr_len:]}"
                )
            temp_bam_entry.query_qualities = (
                temp_read1_entry.query_qualities[o.tag_len + o.spcr_len:]
                )
            temp_bam_entry.set_tag('X?', temp_read1_entry.query_name, 'Z')
            temp_bam.write(temp_bam_entry)

            # Write entries for Read 2
            temp_bam_entry.query_name = temp_bam_entry.query_name.replace(
                '1', '2'
                )
            temp_bam_entry.query_sequence = (
                f"{line.query_sequence[o.tag_len + o.spcr_len:]}"
                )
            temp_bam_entry.query_qualities = (
                line.query_qualities[o.tag_len + o.spcr_len:]
                )
            temp_bam_entry.set_tag('X?', line.query_name, 'Z')
            temp_bam.write(temp_bam_entry)

        paired_end_count += 1

    in_bam_file.close()
    temp_bam.close()

    print("Sorting reads on tag sequence...")

    pysam.sort("-n", o.prefix + ".temp.bam", "-o", o.prefix + ".temp.sort.bam")
    # Sort by read name, which will be the tag sequence in this case.
    os.remove(o.prefix + ".temp.bam")

    '''Extracting tags and sorting based on tag sequence is complete. 
    This block of code now performs the consensus calling on the tag 
    families in the temporary name sorted bam file.
    '''
    
    seq_dict = {'ab:1': [], 'ab:2': [], 'ba:1': [], 'ba:2': []}
    qual_dict = {'ab:1': [], 'ab:2': [], 'ba:1': [], 'ba:2': []}
    fam_size_x_axis = []
    fam_size_y_axis = []

    read1_dcs_len = 0
    read2_dcs_len = 0
    in_bam_file = pysam.AlignmentFile(
        f"{o.prefix}.temp.sort.bam", "rb", check_sq=False
        )
    first_line = next(in_bam_file)
    
    FinalValue = pysam.AlignedSegment()
    FinalValue.query_name = "FinalValue#ab:1"
    
    seq_dict[first_line.query_name.split('#')[1]].append(
        first_line.query_sequence
        )
    qual_dict[first_line.query_name.split('#')[1]].append(
        list(first_line.query_qualities)
        )
    tag_count_dict = defaultdict(lambda: 0)

    print("Creating consensus reads...")

    for line in iteratorWrapper(in_bam_file.fetch(until_eof=True), FinalValue):
        tag = first_line.query_name.split('#')[0]
        subtag_order = first_line.query_name.split('#')[1]
        if line.query_name.split('#')[0] == tag:
            seq_dict[line.query_name.split('#')[1]].append(
                line.query_sequence
                )
            qual_dict[line.query_name.split('#')[1]].append(
                list(line.query_qualities)
                )

        else:

            if (len(seq_dict['ab:1']) != len(seq_dict['ab:2']) 
                    or len(seq_dict['ba:1']) != len(seq_dict['ba:2'])
                    ):
                raise Exception(f'ERROR: Read counts for Read1 and Read 2 do '
                                f'not match for tag {tag}'
                                )

            for tag_subtype in seq_dict.keys():

                if len(seq_dict[tag_subtype]) > 0:
                    tag_count_dict[len(seq_dict[tag_subtype])] += 1

                if len(seq_dict[tag_subtype]) < o.minmem:
                    seq_dict[tag_subtype] = []
                    qual_dict[tag_subtype] = []

                elif o.minmem <= len(seq_dict[tag_subtype]) <= o.maxmem:  
                    # Tag types w/o reads should not be submitted as long as 
                    # minmem is > 0
                    seq_dict[tag_subtype] = [
                        consensus_caller(seq_dict[tag_subtype], 
                                        o.cutoff, 
                                        tag, 
                                        True
                                        ),
                        str(len(seq_dict[tag_subtype]))
                        ]
                    qual_dict[tag_subtype] = qual_calc(qual_dict[tag_subtype])

                elif len(seq_dict[tag_subtype]) > o.maxmem:
                    seq_dict[tag_subtype] = [
                        consensus_caller(seq_dict[tag_subtype][:o.maxmem], 
                                         o.cutoff, 
                                         tag, 
                                         True
                                         ),
                        str(len(seq_dict[tag_subtype]))
                        ]
                    qual_dict[tag_subtype] = qual_calc(qual_dict[tag_subtype])

            if o.write_sscs is True:

                if len(seq_dict['ab:1']) != 0 and len(seq_dict['ab:2']) != 0:
                    corrected_qual_score = map(
                        lambda x: x if x < 41 else 41, qual_dict['ab:1']
                        )
                    corrQualStr = ''.join(
                        chr(x + 33) for x in corrected_qual_score
                        )
                    read1_sscs_fq_file.write(f"@{tag}#ab/1\n"
                                             f"{seq_dict['ab:1'][0]}\n"
                                             f"+{seq_dict['ab:1'][1]}\n"
                                             f"{corrQualStr}\n"
                                             )

                    corrected_qual_score = map(
                        lambda x: x if x < 41 else 41, qual_dict['ab:2']
                        )
                    corrQualStr = ''.join(
                        chr(x + 33) for x in corrected_qual_score
                        )
                    read2_sscs_fq_file.write(f"@{tag}#ab/2\n"
                                             f"{seq_dict['ab:2'][0]}\n"
                                             f"+{seq_dict['ab:2'][1]}\n"
                                             f"{corrQualStr}\n"
                                             )

                if len(seq_dict['ba:1']) != 0 and len(seq_dict['ba:2']) != 0:
                    corrected_qual_score = map(
                        lambda x: x if x < 41 else 41, qual_dict['ba:1']
                        )
                    corrQualStr = ''.join(
                        chr(x + 33) for x in corrected_qual_score
                        )
                    read1_sscs_fq_file.write(f"@{tag}#ba/1\n"
                                             f"{seq_dict['ba:1'][0]}\n"
                                             f"+{seq_dict['ba:1'][1]}\n"
                                             f"{corrQualStr}\n"
                                             )

                    corrected_qual_score = map(
                        lambda x: x if x < 41 else 41, qual_dict['ba:2']
                        )
                    corrQualStr = ''.join(
                        chr(x + 33) for x in corrected_qual_score
                        )
                    read2_sscs_fq_file.write(f"@{tag}#ba/2\n"
                                             f"{seq_dict['ba:2'][0]}\n"
                                             f"+{seq_dict['ba:2'][1]}\n"
                                             f"{corrQualStr}\n"
                                             )

            if o.without_dcs is False:

                if len(seq_dict['ab:1']) != 0 and len(seq_dict['ba:2']) != 0:
                    dcs_read_1 = [
                        consensus_caller(
                            [seq_dict['ab:1'][0], seq_dict['ba:2'][0]], 
                            1, 
                            tag, 
                            False
                            ),
                        seq_dict['ab:1'][1], seq_dict['ba:2'][1]
                        ]
                    dcs_read_1_qual = map(
                        lambda x: x if x < 41 else 41, 
                        qual_calc([qual_dict['ab:1'], qual_dict['ba:2']])
                        )
                    read1_dcs_len = len(dcs_read_1)
                    fam_size_x_axis.append(int(seq_dict['ab:1'][1]))
                    fam_size_y_axis.append(int(seq_dict['ba:2'][1]))

                    if dcs_read_1.count('N')/float(read1_dcs_len) > o.Ncutoff:
                        dcs_read_1 = 'N' * read1_dcs_len
                        dcs_read_1_qual = '!' * read1_dcs_len

                if len(seq_dict['ba:1']) != 0 and len(seq_dict['ab:2']) != 0:
                    dcs_read_2 = [
                        consensus_caller(
                            [seq_dict['ba:1'][0], seq_dict['ab:2'][0]], 
                            1, 
                            tag, 
                            False
                            ),
                        seq_dict['ba:1'][1], seq_dict['ab:2'][1]
                        ]
                    dcs_read_2_qual = map(
                        lambda x: x if x < 41 else 41, 
                        qual_calc([qual_dict['ba:1'], qual_dict['ab:2']])
                        )
                    read2_dcs_len = len(dcs_read_2)

                    if dcs_read_2.count('N')/float(read1_dcs_len) > o.Ncutoff:
                        dcs_read_2 = 'N' * read1_dcs_len
                        dcs_read_2_qual = '!' * read2_dcs_len

                if (read1_dcs_len != 0 
                        and read2_dcs_len != 0 
                        and tag.count('N') == 0 
                        and 'A' * o.rep_filt not in tag 
                        and 'C' * o.rep_filt not in tag 
                        and 'G' * o.rep_filt not in tag 
                        and 'T' * o.rep_filt not in tag
                        ):
                    r1QualStr = ''.join(chr(x + 33) for x in dcs_read_1_qual)
                    r2QualStr = ''.join(chr(x + 33) for x in dcs_read_2_qual)
                    read1_dcs_fq_file.write(
                        f"@{tag}/1\n{dcs_read_1[0]}\n"
                        f"+{dcs_read_1[1]}:{dcs_read_1[2]}\n"
                        f"{r1QualStr}\n"
                        )
                    read2_dcs_fq_file.write(
                        f"@{tag}/2\n{dcs_read_2[0]}\n"
                        f"+{dcs_read_2[1]}:{dcs_read_2[2]}\n"
                        f"{r2QualStr}\n"
                        )
            
            if line != FinalValue:
                
                # reset conditions for next tag family
                first_line = line
                seq_dict = {'ab:1': [], 'ab:2': [], 'ba:1': [], 'ba:2': []}
                qual_dict = {'ab:1': [], 'ab:2': [], 'ba:1': [], 'ba:2': []}
                read1_dcs_len = 0
                read2_dcs_len = 0
                dcs_read_1 = ''
                dcs_read_2 = ''

                seq_dict[line.query_name.split('#')[1]].append(line.query_sequence)
                # Now add initializing data for new tag
                qual_dict[first_line.query_name.split('#')[1]].append(
                    list(first_line.query_qualities)
                    )
    
# Try to plot the tag family sizes
    if o.tagstats is True:
        tag_stats_file = open(o.prefix + ".tagstats.txt", 'w')

        x_value = []
        y_value = []
        total_reads = sum(
            [tag_count_dict[tag_family_size] 
             * tag_family_size for tag_family_size in tag_count_dict.keys()
             ])

        for tag_family_size in sorted(tag_count_dict.keys()):
            fraction = (tag_count_dict[tag_family_size] * tag_family_size) 
            fraction /= float(total_reads)
            tag_stats_file.write(
                f'{tag_family_size}\t'
                f'{tag_count_dict[tag_family_size]}\t'
                f'{fraction}\n'
                )
            x_value.append(tag_family_size)
            y_value.append(fraction)

        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt

            plt.figure(1)
            plt.bar(x_value, y_value)
            plt.xlabel('Family Size')
            plt.ylabel('Proportion of Total Reads')
            plt.savefig(f"{o.prefix}family_size.png", 
                        bbox_inches='tight'
                        )
            if len(fam_size_x_axis) != 0:
                plt.figure(2)
                plt.scatter(fam_size_x_axis, fam_size_y_axis, alpha=.1)
                plt.xlabel('Family size for AB:1')
                plt.ylabel('Family size for BA:2')
                plt.xlim(0, max(fam_size_x_axis))
                plt.ylim(0, max(fam_size_y_axis))
                plt.savefig(f"{o.prefix}fam_size_relation.png", 
                            bbox_inches='tight'
                            )

        except ImportError:
            sys.stderr.write(
                'matplotlib not present. Only tagstats file will be generated.'
                )

        tag_stats_file.close()

if __name__ == "__main__":
    main()
