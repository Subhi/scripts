#!/usr/bin/env python

import heapq
from collections import namedtuple

TAB = '\t'
COLON = ':'
COMMA = ','
SEMI_COLON = ';'
EQUALS = '='

REFERENCE_SAMPLE_SUFFIXES = ( 'R', 'BL','NORMAL' ) # TODO maybe make this command line argument
REQUIRED_VARIANT_FIELDS = ('CHROM', 'POS', 'ID', 'REF', 'ALT', 'QUAL', 'FILTER', 'INFO')
CSV_FIELDS = ('CHROM', 'POS', 'REF', 'ALT', 'TOTAL', 'HET', 'HOM')

def ScriptName():
    from os import path
    return path.basename(__file__)

# basic helper for writing PON as csv
class CSVWriter():

    def __init__(self, file):
        self.file = file
        
    def writeCommentLine(self, sentence):
        self.file.write( '## %s\n' % sentence )
    
    def writeHeaderLine(self):
        self.file.write('#%s\n' % COMMA.join(CSV_FIELDS))

    def writeDataLine(self, *args):
        values = COMMA.join(str(v) for v in args)
        self.file.write( values + '\n')

# basic helper for writing valid VCF files with no samples
class VCFWriter():

    VARIANT_MISSING_FIELD = '.'
    REQUIRED_INFO_DESCRIPTORS = ('ID', 'Number', 'Type', 'Description')
    VALID_INFO_TYPES = ('Integer', 'Float', 'Flag', 'Character', 'String')

    InformationField = namedtuple('InformationField', REQUIRED_INFO_DESCRIPTORS)
    Variant = namedtuple('Variant', REQUIRED_VARIANT_FIELDS)

    def __init__(self, file):
        self.file = file
        self.writeFileHeader()
        self.writeFileDateHeader()
        self.writeSourceHeader()

    def writeFileHeader(self):
        self.file.write('##fileformat=VCFv4.1\n')

    def writeFileDateHeader(self):
        from datetime import date
        self.file.write('##fileDate=%s\n' % date.today().strftime("%Y%m%d"))

    def writeSourceHeader(self):
        self.file.write('##source=%s\n' % ScriptName())

    def writeInfoHeader(self, **kwargs):
        kwargs['Description'] = '"%s"' % kwargs['Description']
        assert kwargs['Type'] in self.VALID_INFO_TYPES
        self.file.write( '##INFO=<%s>\n' % COMMA.join(EQUALS.join((k, str(v))) for k, v in zip(self.InformationField._fields, self.InformationField(**kwargs))) )

    def writeCustomHeader(self, name, value):
        self.file.write( '##%s=%s\n' % (name, value) )

    def writeVariantHeader(self):
        self.file.write('#%s\n' % TAB.join(REQUIRED_VARIANT_FIELDS))

    def writeVariant(self, **kwargs):
        for field in REQUIRED_VARIANT_FIELDS: kwargs.setdefault(field, self.VARIANT_MISSING_FIELD)
        self.file.write(TAB.join(self.Variant(**kwargs)) + '\n')

# basic helper for reading and validating a VCF file
class VCFReader():
    def __init__(self, file):
        self.file = file
        self.headers = []
        self.samples = []
        self.processHeaders()

    def processHeaders(self):
        assert self.file.readline().startswith('##fileformat=VCFv4.')
        while True:
            line = self.file.readline().rstrip()
            assert len(line)
            if line[0:2] == "##":
                self.processMetaInformation(line)
            elif line[0] == "#":
                self.processVariantHeader(line)
                return
            else:
                raise Exception("VCF format derailment")

    def processMetaInformation(self, line):
        pass

    def processVariantHeader(self, line):
        self.headers = line[1:].split(TAB)
        assert self.headers[:8] == list(REQUIRED_VARIANT_FIELDS)
        if len(self.headers) > 8:
            assert self.headers[8] == 'FORMAT'
            self.samples = self.headers[9:]
        self.tuple = namedtuple('VCFReaderVariant', self.headers)

    def readVariant(self):
        line = self.file.readline()
        return self.tuple._make(line.rstrip().split(TAB)) if line else None

    def readVariantMatchingFilter(self, filter):
        variant = self.readVariant()
        while variant and not filter(variant):
            variant = self.readVariant()
        return variant

    def getSamples(self):
        return self.samples

    def setReferenceSample(self, sample):
        self.reference_idx = self.headers.index(sample)

    def getReferenceSampleFromVariant(self, variant):
        return variant[self.reference_idx]

class PONGenerator():

    def __init__(self, outputFile, outputFileCsv, minCountThreshold,strelkaMode):
        self._heap = []
        self._outputFile = outputFile
        self._minCountThreshold = minCountThreshold
        self._strelkaMode = strelkaMode
        
        ## PON vcf file
        self._outputFile.writeInfoHeader(ID="PON_COUNT", Number=1, Type="Integer", Description="how many samples had the variant")
        self._outputFile.writeInfoHeader(ID="PON_HET", Number=1, Type="Integer", Description="how many samples had genotype heterozygous alt")
        self._outputFile.writeInfoHeader(ID="PON_HOM", Number=1, Type="Integer", Description="how many samples had genotype homozygous alt")
        
        ## additionally write data as CSV
        self._outCsvFile = outputFileCsv
        self._outCsvFile.writeCommentLine( "TOTAL: how many samples had alt" )
        self._outCsvFile.writeCommentLine( "HET: how many samples had alt with heterozygous genotype alt" )
        self._outCsvFile.writeCommentLine( "HOM: how many samples had alt with homozygous genotype" )

    def merge(self, vcf_readers):
        def readAndPushVariant(vcf):
            done = False
            while not done:
                var = vcf.readVariant()
                if var is None: return
                done = self.pushVariantToHeap(var, vcf)

        samples = set()
        for vcf in vcf_readers:
            # find the reference sample
            sample = next(s for s in vcf.getSamples() for suffix in REFERENCE_SAMPLE_SUFFIXES if s.endswith(suffix))
            if sample in samples and not self._strelkaMode: # check it is unique
                continue
            samples.add(sample)
            vcf.setReferenceSample( sample )
            # prime the heap
            readAndPushVariant(vcf)

        # finalise headers
        sampleCount = len(samples)
        self._outputFile.writeCustomHeader("PonInputSampleCount", sampleCount)
        self._outputFile.writeVariantHeader()
        self._outCsvFile.writeCommentLine("PonInputSampleCount: %i" % sampleCount)
        self._outCsvFile.writeCommentLine("PonInputSamples: %s" % COMMA.join(samples))
        self._outCsvFile.writeHeaderLine()

        previousCount = 0
        prevHetCount  = 0
        prevHomCount  = 0
        prevOthCount  = 0
        location, variant, alt, genotype_of_alt, vcf = self._heap[0]

        while self._heap:

            previousLocation, previousVariant, previousAlt = location, variant, alt
            location, variant, alt, genotype_of_alt, vcf = heapq.heappop(self._heap)

            if location > previousLocation:

                self.writeToOutput(previousVariant, previousAlt, previousCount, prevHetCount, prevHomCount)
                
                ## re-init all counts
                previousCount = 0
                prevHetCount  = 0
                prevHomCount  = 0
                prevOthCount  = 0
                
                if genotype_of_alt == 'HetAlt':
                    previousCount = 1
                    prevHetCount = 1
                elif genotype_of_alt == 'HomAlt':
                    previousCount = 1
                    prevHomCount = 1
                elif genotype_of_alt == 'Other':
                    prevOthCount = 1
                else:
                    raise Exception('WARNING Unexpected genotype_of_alt found: ' + str(genotype_of_alt) )
                    
            else:
                
                if genotype_of_alt == 'HetAlt':
                    previousCount += 1
                    prevHetCount += 1
                elif genotype_of_alt == 'HomAlt':
                    previousCount += 1
                    prevHomCount += 1
                elif genotype_of_alt == 'Other':
                    prevOthCount += 1
                else:
                    raise Exception('WARNING Unexpected genotype_of_alt found: ' + str(genotype_of_alt) )
           
            if vcf:
                readAndPushVariant(vcf)

        self.writeToOutput(variant, alt, previousCount, prevHetCount, prevHomCount)

    def pushVariantToHeap(self, variant, vcf):
        def chromosomeToNumber(chromosome):
            if chromosome == 'X':
                return 23
            elif chromosome == 'Y':
                return 24
            elif chromosome == 'MT':
                return 25
            else:
                return int(chromosome)

        if self._strelkaMode:
            refSampleSplit = vcf.getReferenceSampleFromVariant(variant).split(COLON)
            formatSplit = variant.FORMAT.split(COLON)

            if variant.ALT == ".":
                return False
            alt = variant.ALT.split(COMMA)[0]
            if (len(variant.REF)==len(alt)):
                if int(refSampleSplit[formatSplit.index(alt+ 'U')].split(',')[1]) > 1:
                    heapq.heappush(self._heap,
                                (
                                   (chromosomeToNumber(variant.CHROM), int(variant.POS), hash(variant.REF), hash(alt)),
                                   variant,
                                   alt,
                                   'HetAlt',
                                   vcf
                               )
                               )
                    return True
            else:
                if int(refSampleSplit[formatSplit.index('TIR')].split(',')[1]) > 1:
                    heapq.heappush(self._heap,
                                   (
                                       (chromosomeToNumber(variant.CHROM), int(variant.POS), hash(variant.REF), hash(alt)),
                                       variant,
                                       alt,
                                       'HetAlt',
                                       vcf
                                   )
                                   )
                    return True

            return False

        # check that reference sample shows the alt in GT field
        else:
            refSampleGenotypeString = vcf.getReferenceSampleFromVariant(variant).split(COLON, 1)[0]
            altString = variant.ALT
            alts = variant.ALT.split(COMMA)
            
            for idx, alt in enumerate(variant.ALT.split(COMMA)):
                
                alt_int = idx+1
                alt_count = refSampleGenotypeString.count( str(alt_int) )
                genotype_of_alt = 'NA'
                
                if alt_count == 2:
                    genotype_of_alt = 'HomAlt'
                elif alt_count == 1:
                    genotype_of_alt = 'HetAlt'
                else:
                    genotype_of_alt = 'Other'
                    
                heapq.heappush(self._heap,
                    (
                        (chromosomeToNumber(variant.CHROM), int(variant.POS), hash(variant.REF), hash(alt)), # location tuple, sorted on this field
                        variant,
                        alt,
                        genotype_of_alt,
                        vcf if idx==len(alts)-1 else None
                    )
                )
            return len(alts) > 0

    def writeToOutput(self, variant, alt, poncount, hetcount, homcount):
        if poncount < self._minCountThreshold:
            return
        self._outputFile.writeVariant(
            CHROM = variant.CHROM,
            POS = variant.POS,
            REF = variant.REF,
            ALT = alt,
            FILTER = 'PASS',
            INFO = 'PON_COUNT=%i;PON_HET=%i;PON_HOM=%i' % (poncount, hetcount, homcount)
        )
        self._outCsvFile.writeDataLine( 
            variant.CHROM, variant.POS, variant.REF, alt, poncount, hetcount, homcount
        )

if __name__ == '__main__':

    import argparse
    parser = argparse.ArgumentParser(
        description="Generates a Panel of Normals (PON) VCF file",
        formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=100, width=200)
    )
    required = parser.add_argument_group('required arguments')
    required.add_argument('-m', '--minCountThreshold', help='minCount to add to PON output. eg: 2', required=True, type=int)
    required.add_argument('-o', '--outputFile', help='output vcf file name', required=True, type=argparse.FileType('w'))
    required.add_argument('-c', '--outCsvFile', help='output csv file name', required=True, type=argparse.FileType('w'))
    required.add_argument('-i', '--inputFiles', nargs='+', help='list of vcf files to merge', required=True, type=argparse.FileType('r'))

    optional = parser.add_argument_group('optional arguments')
    optional.add_argument('-s','--strelka', type=bool, nargs='?',
                          const=True, default=False,
                          help="Run for Strelka Somatic Output")
    args = parser.parse_args()

    try:
        if args.strelka == True:
            print("Running in Strelka Mode")
        vcfFile = args.outputFile
        csvFile = args.outCsvFile
        generator = PONGenerator( VCFWriter(vcfFile), CSVWriter(csvFile), args.minCountThreshold,args.strelka )
        generator.merge( VCFReader(f) for f in args.inputFiles )
    finally: # be a good citizen
        args.outputFile.close()
        for f in args.inputFiles: f.close()
