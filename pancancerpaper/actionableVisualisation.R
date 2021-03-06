library(ggplot2)
library(dplyr)
library(tidyr)
library(scales)
library(cowplot)
theme_set(theme_bw() + theme(axis.text=element_text(size=5),axis.title=element_text(size=5), legend.text = element_text(size=5)))

########################################### Prepare Data
alphabetical_drug <- function(drugs) {
  result = c()
  for (i in 1:length(drugs)) {
    drug = drugs[i]
    sortedDrugList = sort(unlist(strsplit(drug, " + ", fixed = T)))
    result[i] <- paste(sortedDrugList, collapse = " + ")
  }
  return (result)
}

levelTreatmentFactors = c("None","B_OffLabel","B_OnLabel","A_OffLabel","A_OnLabel")
levelTreatmentColors = setNames(c("black", "#eff3ff", "#bdd7e7","#6baed6", "#2171b5"), levelTreatmentFactors)

actionableVariantsPerSample = read.csv('~/hmf/resources/actionableVariantsPerSample.tsv',header=T,sep = '\t', stringsAsFactors = F) %>%
  filter(!gene %in% c('PTEN','KRAS'),
         hmfLevel %in% c('A','B')) %>%
  mutate(
    treatmentType = ifelse(treatmentType == "Unknown", "OffLabel", treatmentType),
    drug = ifelse(drug == "Fluvestrant", "Fulvestrant", drug),
    drug = ifelse(drug == "Ado-trastuzumab Emtansine", "Ado-Trastuzumab Emtansine", drug),
    drug = ifelse(drug == "AZD4547", "AZD-4547", drug),
    drug = ifelse(drug == "AZD5363", "AZD-5363", drug),
    drug = ifelse(drug == "BGJ398", "BGJ-398", drug),
    drug = alphabetical_drug(drug),
    eventType = ifelse(eventType == "SNP", "SNV", eventType),
    eventType = ifelse(eventType == "MNP", "MNV", eventType),
    levelTreatment = factor(paste(hmfLevel, treatmentType, sep = "_"), levelTreatmentFactors, ordered = T))

actionableVariantsPerSample = actionableVariantsPerSample %>% 
  mutate(gene = ifelse(eventType == "Fusion", paste0(gene, " - ", partnerGene), gene)) 

load(file = '~/hmf/RData/Processed/highestPurityCohortSummary.RData')
pembrolizumabVariants = highestPurityCohortSummary %>% 
  filter(msiStatus == 'MSI') %>% 
  select(sampleId, patientCancerType = cancerType) %>% 
  mutate(
    drug = "Pembrolizumab", 
    levelTreatment = factor("A_OnLabel", levelTreatmentFactors, ordered = T),
    gene = "",eventType = "MSI", pHgvs = "", hmfResponse= "Responsive")

nivolumabVariants = highestPurityCohortSummary %>% 
  filter(msiStatus == 'MSI') %>% 
  select(sampleId, patientCancerType = cancerType) %>% 
  mutate(
    drug = "Nivolumab", 
    levelTreatment = factor(ifelse(patientCancerType == "Colon/Rectum", "A_OnLabel", "A_OffLabel"), levelTreatmentFactors, ordered = T),
    gene = "",eventType = "MSI", pHgvs = "", hmfResponse= "Responsive")

actionableVariants = actionableVariantsPerSample %>% select(sampleId, patientCancerType, drug, levelTreatment, gene, eventType, pHgvs, hmfResponse) %>%
  bind_rows(pembrolizumabVariants) %>%
  bind_rows(nivolumabVariants)
  
########################################### Supplementary Data
drugResponse <- function(actionableVariants, response) {
  actionableVariants %>% 
    filter(hmfResponse == response) %>%
    group_by(sampleId,patientCancerType, drug) %>%
    summarise(levelTreatment = max(levelTreatment)) %>%
  ungroup()
}

responsiveDrugs = drugResponse(actionableVariants, 'Responsive') %>% mutate(response = levelTreatment) %>% select(-levelTreatment)
resistantDrugs = drugResponse(actionableVariants, 'Resistant') %>% mutate(resistance = levelTreatment) %>% select(-levelTreatment)

actionableDrugs = merge(responsiveDrugs,resistantDrugs,by=c('sampleId','patientCancerType','drug'),all=T,suffixes=c('_Response','_Resistance'), fill=0) %>%
  filter(is.na(resistance) | response > resistance) %>% 
  replace_na(list(resistance = "None"))

responsiveVariants = actionableDrugs %>% 
  left_join(actionableVariants, by = c("sampleId", "patientCancerType","drug")) %>%
  filter(levelTreatment > resistance) %>%
  mutate(cancerType = patientCancerType) %>%
  group_by(sampleId, cancerType, gene, eventType, pHgvs, drug) %>%
  summarise(levelTreatment = max(levelTreatment)) %>%
  group_by(sampleId, cancerType, gene, eventType, pHgvs, levelTreatment) %>%
  summarise(drug = paste(drug, collapse = ";")) %>%
  spread(levelTreatment, drug, fill = "") %>%
  ungroup() 
save(responsiveVariants, file = "~/hmf/RData/Processed/responsiveVariants.RData")

#### SUPPLEMENTARY TABLE
load(file = "~/hmf/RData/Processed/responsiveVariants.RData")
sampleIdMap = read.csv(file = "/Users/jon/hmf/secure/SampleIdMap.csv", stringsAsFactors = F)
actionability = responsiveVariants %>% left_join(sampleIdMap, by = "sampleId") %>%
  select(-sampleId) %>%
  select(sampleId = hmfSampleId, everything())
write.csv(actionability, file = "~/hmf/RData/Supp/Supplementary Table 9_Actionability.csv", row.names = F)

geneResponseSummary = responsiveVariants %>% ungroup() %>% distinct(sampleId, gene) %>% group_by(gene) %>% count()
drugResponseSummary = responsiveVariants %>% ungroup() %>% distinct(sampleId, drug) %>% group_by(drug) %>% count()
#PLATINUM v Platinum Agent ??
#Binimetinib v Binimetinib (MEK162) v Binimetinib + Ribociclib
#Alpelisib v Alpelisib + Fulvestrant
#Buparlisib v Buparlisib + Fulvestrant
#Dabrafenib v Dabrafenib + Trametinib

########################################### Visualise
load(file = '~/hmf/RData/Reference/hpcCancerTypeCounts.RData')
load(file = "~/hmf/RData/Processed/responsiveVariants.RData")

actionablePlotData = responsiveVariants  %>%
  mutate(
    response = ifelse(B_OnLabel != "", "B_OnLabel", "B_OffLabel"),
    response = ifelse(A_OffLabel != "", "A_OffLabel", response),
    response = ifelse(A_OnLabel != "", "A_OnLabel", response),
    response = factor(response, levelTreatmentFactors)) %>%
  group_by(sampleId, cancerType) %>% arrange(response) %>% summarise(response = last(response)) %>%
  group_by(cancerType, response) %>% count() %>% arrange(cancerType, response) %>%
  left_join(hpcCancerTypeCounts %>% select(cancerType, N), by = "cancerType" ) %>% 
  mutate(percentage = n/N) %>%
  arrange(cancerType, response)

actionablePlotDataFactors = actionablePlotData %>% 
  select(cancerType, response, n, N) %>%
  group_by(cancerType) %>% 
  spread(response, n, fill = 0) %>%
  mutate(
    APercent = (A_OffLabel + A_OnLabel) / N,
    BPercent = B_OnLabel / N) %>%
  arrange(APercent, BPercent)

actionablePlotData = actionablePlotData %>% 
  ungroup() %>%
  mutate(cancerType = factor(cancerType, actionablePlotDataFactors$cancerType))

p1 = ggplot(data = actionablePlotData, aes(x = cancerType, y = percentage)) +
  geom_bar(stat = "identity", aes(fill = response)) + 
  scale_fill_manual(values = levelTreatmentColors, guide = guide_legend(reverse = TRUE)) +
  xlab("") + ylab("% with treatment options") +
  scale_y_continuous(labels = percent, limits = c(0, 1), expand = c(0.02,0)) +
  theme(panel.grid.major.y = element_blank(), panel.grid.minor = element_blank(), panel.border = element_blank()) +
  theme(plot.margin = margin(2,3,0,0,unit = "pt")) +
  theme(legend.position = c(0.75, 0.1), legend.title = element_blank(),  legend.key.size = unit(0.2, "cm"), legend.margin = margin(0,0,0,0,unit = "pt")) +
  theme(axis.ticks = element_blank()) +
  guides(fill = guide_legend(ncol = 1, reverse = T)) + 
  theme(legend.spacing.x = unit(4, 'pt')) +
  coord_flip()
p1

########################################### Figure 8 part 2 - Actionable Pie
library(ggforce) 

load(file = "~/hmf/RData/reference/simplifiedDrivers.RData")
actionableDriverColours = simplifiedDriverColours[c("Amplification", "Fusion", "Indel", "Missense", "Nonsense", "Deletion")]
names(actionableDriverColours) <- c("Amplification", "Fusion", "Indel","SNV","MSI","MNV")

load(file = "~/hmf/RData/Processed/responsiveVariants.RData")
eventTypeFactor = c("SNV","MSI","Amplification","MNV","Indel","Fusion")
responseChartData = responsiveVariants %>% 
  mutate(eventType = ifelse(eventType == "INDEL", "Indel", eventType)) %>%
  mutate(eventType = factor(eventType, eventTypeFactor, ordered = T)) %>% arrange(eventType) %>%
  group_by(eventType) %>% 
  dplyr::count() %>% 
  ungroup() %>% 
  mutate(share = n / sum(n))

responseChartData = responseChartData %>% 
  mutate(end = 2 * pi * cumsum(share)/sum(share),
         start = lag(end, default = 0),
         middle = 0.5 * (start + end),
         hjust = ifelse(middle > pi, 1, 0),
         vjust = ifelse(middle < pi/2 | middle > 3 * pi/2, 0, 1))

responseChartData$xOffset <- ifelse(responseChartData$eventType == "XX", -0.1, 0)
responseChartData$yOffset <- ifelse(responseChartData$eventType == "XX", -0.1, 0)

pie = ggplot(responseChartData) + 
  geom_arc_bar(aes(x0 = 0, y0 = 0, r0 = 0, r = 1, start = start, end = end, fill = eventType), size = 0.01, alpha = 1) +
  geom_text(aes(x = 1.17 * sin(middle) + xOffset, y = 1.17 * cos(middle) + yOffset, label = paste0(round(responseChartData$share*100, 1), "%"), hjust = 0.5, vjust = 0.5), size = 5* 25.4 / 72) +
  coord_fixed() +
  scale_x_continuous(name = "", breaks = NULL, labels = NULL, limits = c(-1.3, 1.3)) +
  scale_y_continuous( name = "", breaks = NULL, labels = NULL) +
  theme(
    panel.grid.major.y = element_blank(), panel.grid.minor = element_blank(), panel.border = element_blank(), 
    legend.position = c(0.5, -0.05),  legend.key.size = unit(0.2, "cm"), legend.title = element_blank(), legend.background = element_blank()) +
  theme(legend.spacing.x = unit(2, 'pt')) +
  theme(plot.margin = margin(t = 2,0,0,00,unit = "pt")) +
  scale_fill_manual(values = actionableDriverColours, name = "Variant Type") +
  guides(fill = guide_legend(nrow = 2)) 
pie

pActionability = plot_grid(p1, pie, nrow = 1, labels = "auto", rel_widths = c(4, 4), label_size = 8)
pActionability

ggplot2::ggsave("~/hmf/RPlot/Figure 5.pdf", pActionability, width = 94, height = 50, units = "mm", dpi = 300)
ggplot2::ggsave("~/hmf/RPlot/Figure 5.png", pActionability, width = 94, height = 50, units = "mm", dpi = 300)
#convert -density 300 ~/hmf/RPlot/Figure\ 5.png ~/hmf/RPlot/Figure\ 5.pdf
#ggplot2::ggsave("~/hmf/RPlot/Figure 5b.pdf", pActionability, width = 89, height = 70, units = "mm", dpi = 300)


#pdf(file = "~/hmf/RPlot/Figure 5.pdf", width = 89/10/2.54, height = 70/10/2.54)
#pActionability
#dev.off()

pActionability
save_plot("~/hmf/RPlot/Figure 8 - Actionable.png", pActionability, base_width = 16, base_height = 8)

