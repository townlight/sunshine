"""Seed exemption rules for all 50 states + DC."""
import asyncio
from townlight_records.database import async_session_maker
from townlight_records.models.exemption import ExemptionRule, RuleType
from townlight_records.models.user import User
from sqlalchemy import select

COLORADO_CORA_RULES = [
    {"category": "CORA - Trade Secrets", "rule_type": "keyword", "definition": "trade secret,proprietary,confidential business,competitive advantage"},
    {"category": "CORA - Personnel Records", "rule_type": "keyword", "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination"},
    {"category": "CORA - Law Enforcement", "rule_type": "keyword", "definition": "investigation,informant,undercover,surveillance,criminal intelligence"},
    {"category": "CORA - Attorney-Client", "rule_type": "keyword", "definition": "attorney-client,legal privilege,work product,litigation hold,legal opinion"},
    {"category": "CORA - Deliberative Process", "rule_type": "keyword", "definition": "draft recommendation,preliminary analysis,internal deliberation,policy discussion"},
    {"category": "CORA - Medical Records", "rule_type": "keyword", "definition": "medical record,patient,diagnosis,treatment plan,HIPAA,health information"},
    {"category": "CORA - Student Records", "rule_type": "keyword", "definition": "student record,FERPA,academic record,enrollment,grade,transcript"},
    {"category": "CORA - Real Estate Appraisal", "rule_type": "keyword", "definition": "appraisal,property valuation,assessed value,market analysis"},
]

# Texas Public Information Act (TPIA) — Tex. Gov't Code Ch. 552
TEXAS_TPIA_RULES = [
    {
        "category": "TPIA - Personnel Records",
        "rule_type": "keyword",
        "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination,home address,social security",
        "description": "Texas TPIA exemption: Personnel Records (Tex. Gov't Code § 552.102)",
    },
    {
        "category": "TPIA - Law Enforcement",
        "rule_type": "keyword",
        "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement sensitive,offense report",
        "description": "Texas TPIA exemption: Law Enforcement Records (Tex. Gov't Code § 552.108)",
    },
    {
        "category": "TPIA - Litigation Privilege",
        "rule_type": "keyword",
        "definition": "pending litigation,lawsuit,legal claim,settlement negotiation,litigation hold,judicial proceeding",
        "description": "Texas TPIA exemption: Litigation Privilege (Tex. Gov't Code § 552.103)",
    },
    {
        "category": "TPIA - Trade Secrets",
        "rule_type": "keyword",
        "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
        "description": "Texas TPIA exemption: Trade Secrets and Commercial Information (Tex. Gov't Code § 552.110)",
    },
    {
        "category": "TPIA - Student Records",
        "rule_type": "keyword",
        "definition": "student record,FERPA,academic record,enrollment,grade,transcript,educational record",
        "description": "Texas TPIA exemption: Student Records (Tex. Gov't Code § 552.114)",
    },
    {
        "category": "TPIA - Deliberative Process",
        "rule_type": "keyword",
        "definition": "draft recommendation,preliminary analysis,internal deliberation,policy discussion,predecisional,interagency memo",
        "description": "Texas TPIA exemption: Deliberative Process (Tex. Gov't Code § 552.111)",
    },
    {
        "category": "TPIA - Attorney-Client",
        "rule_type": "keyword",
        "definition": "attorney-client,legal privilege,work product,legal opinion,attorney advice,privileged communication",
        "description": "Texas TPIA exemption: Attorney-Client Privilege (Tex. Gov't Code § 552.107)",
    },
    {
        "category": "TPIA - Personal Privacy",
        "rule_type": "keyword",
        "definition": "personal family information,highly intimate,private information,unwarranted invasion of privacy",
        "description": "Texas TPIA exemption: Personal Privacy (Tex. Gov't Code § 552.101)",
    },
]

# California Public Records Act (CPRA) — Cal. Gov't Code § 7920 et seq.
CALIFORNIA_CPRA_RULES = [
    {
        "category": "CPRA - Personnel Records",
        "rule_type": "keyword",
        "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination,personnel record",
        "description": "California CPRA exemption: Personnel Records (Cal. Gov't Code § 7928.200)",
    },
    {
        "category": "CPRA - Law Enforcement Investigation",
        "rule_type": "keyword",
        "definition": "investigation,informant,undercover,surveillance,criminal intelligence,active investigation,peace officer",
        "description": "California CPRA exemption: Law Enforcement Investigation (Cal. Gov't Code § 7923.600)",
    },
    {
        "category": "CPRA - Attorney-Client",
        "rule_type": "keyword",
        "definition": "attorney-client,legal privilege,work product,litigation hold,legal opinion,attorney advice",
        "description": "California CPRA exemption: Attorney-Client Privilege (Cal. Evid. Code § 954; Cal. Gov't Code § 7927.705)",
    },
    {
        "category": "CPRA - Trade Secrets",
        "rule_type": "keyword",
        "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
        "description": "California CPRA exemption: Trade Secrets (Cal. Gov't Code § 7927.705)",
    },
    {
        "category": "CPRA - Medical and Mental Health",
        "rule_type": "keyword",
        "definition": "medical record,patient,diagnosis,treatment plan,HIPAA,mental health,psychiatric,health information",
        "description": "California CPRA exemption: Medical/Mental Health Records (Cal. Gov't Code § 7928.000)",
    },
    {
        "category": "CPRA - Deliberative Process",
        "rule_type": "keyword",
        "definition": "draft recommendation,preliminary analysis,internal deliberation,policy discussion,predecisional,staff analysis",
        "description": "California CPRA exemption: Deliberative Process / Pre-decisional (Cal. Gov't Code § 7927.705)",
    },
    {
        "category": "CPRA - Personal Information",
        "rule_type": "keyword",
        "definition": "home address,telephone number,personal information,unwarranted invasion of privacy,financial information",
        "description": "California CPRA exemption: Personal Information / Privacy (Cal. Gov't Code § 7922.000)",
    },
]

# New York Freedom of Information Law (FOIL) — N.Y. Pub. Off. Law § 84 et seq.
NEW_YORK_FOIL_RULES = [
    {
        "category": "FOIL - Law Enforcement Investigation",
        "rule_type": "keyword",
        "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement record,active investigation",
        "description": "New York FOIL exemption: Law Enforcement Investigation (N.Y. Pub. Off. Law § 87(2)(e))",
    },
    {
        "category": "FOIL - Trade Secrets",
        "rule_type": "keyword",
        "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information,business secrets",
        "description": "New York FOIL exemption: Trade Secrets (N.Y. Pub. Off. Law § 87(2)(d))",
    },
    {
        "category": "FOIL - Personnel Records",
        "rule_type": "keyword",
        "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination,employment record",
        "description": "New York FOIL exemption: Personnel Records (N.Y. Pub. Off. Law § 87(2)(b); Civil Service Law § 50-a)",
    },
    {
        "category": "FOIL - Attorney-Client",
        "rule_type": "keyword",
        "definition": "attorney-client,legal privilege,work product,legal opinion,attorney advice,privileged communication",
        "description": "New York FOIL exemption: Attorney-Client Privilege (N.Y. Pub. Off. Law § 87(2)(a); CPLR § 4503)",
    },
    {
        "category": "FOIL - Medical Records",
        "rule_type": "keyword",
        "definition": "medical record,patient,diagnosis,treatment plan,HIPAA,health information,medical history",
        "description": "New York FOIL exemption: Medical Records (N.Y. Pub. Off. Law § 87(2)(b))",
    },
    {
        "category": "FOIL - Inter-Agency Communications",
        "rule_type": "keyword",
        "definition": "inter-agency,intra-agency,internal memo,predecisional,deliberative,policy discussion,draft recommendation",
        "description": "New York FOIL exemption: Inter/Intra-Agency Communications (N.Y. Pub. Off. Law § 87(2)(g))",
    },
    {
        "category": "FOIL - Personal Privacy",
        "rule_type": "keyword",
        "definition": "unwarranted invasion of privacy,personal information,home address,financial record,private information",
        "description": "New York FOIL exemption: Personal Privacy (N.Y. Pub. Off. Law § 87(2)(b))",
    },
]

# Florida Sunshine Law / Public Records Act — Fla. Stat. Ch. 119
FLORIDA_PRA_RULES = [
    {
        "category": "FL PRA - Law Enforcement Active Investigation",
        "rule_type": "keyword",
        "definition": "active investigation,criminal investigation,informant,undercover,surveillance,law enforcement sensitive,criminal intelligence",
        "description": "Florida Public Records Act exemption: Active Criminal Investigation (Fla. Stat. § 119.071(2)(c))",
    },
    {
        "category": "FL PRA - Trade Secrets",
        "rule_type": "keyword",
        "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information,business secrets",
        "description": "Florida Public Records Act exemption: Trade Secrets (Fla. Stat. § 119.071(1)(f))",
    },
    {
        "category": "FL PRA - Personnel Records",
        "rule_type": "keyword",
        "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination,employment record",
        "description": "Florida Public Records Act exemption: Personnel Records (Fla. Stat. § 119.071(4)(d))",
    },
    {
        "category": "FL PRA - Social Security Numbers",
        "rule_type": "keyword",
        "definition": "social security number,SSN,tax identification,federal identification number",
        "description": "Florida Public Records Act exemption: Social Security Numbers (Fla. Stat. § 119.071(5)(a))",
    },
    {
        "category": "FL PRA - Medical Records",
        "rule_type": "keyword",
        "definition": "medical record,patient,diagnosis,treatment plan,HIPAA,health information,medical history,mental health",
        "description": "Florida Public Records Act exemption: Medical Records (Fla. Stat. § 119.071(4)(a))",
    },
    {
        "category": "FL PRA - Attorney Work Product",
        "rule_type": "keyword",
        "definition": "attorney work product,legal privilege,attorney-client,litigation hold,legal opinion,attorney advice,work product doctrine",
        "description": "Florida Public Records Act exemption: Attorney Work Product / Client Privilege (Fla. Stat. § 119.071(1)(d))",
    },
    {
        "category": "FL PRA - Home Addresses and Personal Safety",
        "rule_type": "keyword",
        "definition": "home address,personal address,residential address,location information,address confidentiality",
        "description": "Florida Public Records Act exemption: Home Addresses / Personal Safety (Fla. Stat. § 119.071(4)(d)2)",
    },
]

# Alabama Open Records Act
ALABAMA_RULES = [
    {"category": "AL ORA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement sensitive",
     "description": "Alabama Open Records Act exemption: Law Enforcement Records"},
    {"category": "AL ORA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Alabama Open Records Act exemption: Personnel Records"},
    {"category": "AL ORA - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Alabama Open Records Act exemption: Trade Secrets"},
]

# Alaska Public Records Act
ALASKA_RULES = [
    {"category": "AK PRA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "Alaska Public Records Act exemption: Law Enforcement Records"},
    {"category": "AK PRA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Alaska Public Records Act exemption: Personnel Records"},
    {"category": "AK PRA - Personal Privacy", "rule_type": "keyword",
     "definition": "personal information,home address,financial record,unwarranted invasion of privacy",
     "description": "Alaska Public Records Act exemption: Personal Privacy"},
]

# Arizona Public Records Law
ARIZONA_RULES = [
    {"category": "AZ PRL - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement record",
     "description": "Arizona Public Records Law exemption: Law Enforcement Records"},
    {"category": "AZ PRL - Attorney-Client", "rule_type": "keyword",
     "definition": "attorney-client,legal privilege,work product,legal opinion,attorney advice",
     "description": "Arizona Public Records Law exemption: Attorney-Client Privilege"},
    {"category": "AZ PRL - Personal Privacy", "rule_type": "keyword",
     "definition": "personal information,home address,financial record,private information,unwarranted invasion",
     "description": "Arizona Public Records Law exemption: Personal Privacy"},
]

# Arkansas FOIA
ARKANSAS_RULES = [
    {"category": "AR FOIA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "Arkansas FOIA exemption: Law Enforcement Records"},
    {"category": "AR FOIA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Arkansas FOIA exemption: Personnel Records"},
    {"category": "AR FOIA - Medical Records", "rule_type": "keyword",
     "definition": "medical record,patient,diagnosis,treatment plan,HIPAA,health information",
     "description": "Arkansas FOIA exemption: Medical Records"},
]

# Connecticut FOIA
CONNECTICUT_RULES = [
    {"category": "CT FOIA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement record",
     "description": "Connecticut FOIA exemption: Law Enforcement Records"},
    {"category": "CT FOIA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination,medical information",
     "description": "Connecticut FOIA exemption: Personnel/Medical Records"},
    {"category": "CT FOIA - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Connecticut FOIA exemption: Trade Secrets"},
]

# Delaware FOIA
DELAWARE_RULES = [
    {"category": "DE FOIA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "Delaware FOIA exemption: Law Enforcement Records"},
    {"category": "DE FOIA - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Delaware FOIA exemption: Trade Secrets"},
    {"category": "DE FOIA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Delaware FOIA exemption: Personnel Records"},
]

# DC FOIA
DC_RULES = [
    {"category": "DC FOIA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement record",
     "description": "DC FOIA exemption: Law Enforcement Records"},
    {"category": "DC FOIA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "DC FOIA exemption: Personnel Records"},
    {"category": "DC FOIA - Attorney-Client", "rule_type": "keyword",
     "definition": "attorney-client,legal privilege,work product,legal opinion,attorney advice,privileged communication",
     "description": "DC FOIA exemption: Attorney-Client Privilege"},
]

# Georgia Open Records Act
GEORGIA_RULES = [
    {"category": "GA ORA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,pending investigation",
     "description": "Georgia Open Records Act exemption: Law Enforcement Records"},
    {"category": "GA ORA - Medical Records", "rule_type": "keyword",
     "definition": "medical record,patient,diagnosis,treatment plan,HIPAA,health information",
     "description": "Georgia Open Records Act exemption: Medical Records"},
    {"category": "GA ORA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Georgia Open Records Act exemption: Personnel Records"},
]

# Hawaii Uniform Information Practices Act (UIPA)
HAWAII_RULES = [
    {"category": "HI UIPA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "Hawaii UIPA exemption: Law Enforcement Records"},
    {"category": "HI UIPA - Personal Privacy", "rule_type": "keyword",
     "definition": "personal information,home address,financial record,private information,clearly unwarranted invasion",
     "description": "Hawaii UIPA exemption: Personal Privacy"},
    {"category": "HI UIPA - Deliberative Process", "rule_type": "keyword",
     "definition": "draft recommendation,preliminary analysis,internal deliberation,policy discussion,predecisional",
     "description": "Hawaii UIPA exemption: Deliberative Process"},
]

# Idaho Public Records Act
IDAHO_RULES = [
    {"category": "ID PRA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement record",
     "description": "Idaho Public Records Act exemption: Law Enforcement Records"},
    {"category": "ID PRA - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Idaho Public Records Act exemption: Trade Secrets"},
    {"category": "ID PRA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Idaho Public Records Act exemption: Personnel Records"},
]

# Illinois FOIA
ILLINOIS_RULES = [
    {"category": "IL FOIA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement record",
     "description": "Illinois FOIA exemption: Law Enforcement Records (5 ILCS 140/7(1)(d))"},
    {"category": "IL FOIA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Illinois FOIA exemption: Personnel Records (5 ILCS 140/7(1)(b))"},
    {"category": "IL FOIA - Deliberative Process", "rule_type": "keyword",
     "definition": "draft recommendation,preliminary analysis,internal deliberation,policy discussion,predecisional",
     "description": "Illinois FOIA exemption: Deliberative Process (5 ILCS 140/7(1)(f))"},
]

# Indiana Access to Public Records Act
INDIANA_RULES = [
    {"category": "IN APRA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,investigatory record",
     "description": "Indiana Access to Public Records Act exemption: Law Enforcement Records"},
    {"category": "IN APRA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Indiana Access to Public Records Act exemption: Personnel Records"},
    {"category": "IN APRA - Deliberative Process", "rule_type": "keyword",
     "definition": "draft recommendation,preliminary analysis,internal deliberation,policy discussion,predecisional",
     "description": "Indiana Access to Public Records Act exemption: Deliberative Process"},
]

# Iowa Open Records Act
IOWA_RULES = [
    {"category": "IA ORA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "Iowa Open Records Act exemption: Law Enforcement Records"},
    {"category": "IA ORA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Iowa Open Records Act exemption: Personnel Records"},
    {"category": "IA ORA - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Iowa Open Records Act exemption: Trade Secrets"},
]

# Kansas Open Records Act
KANSAS_RULES = [
    {"category": "KS ORA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,criminal investigation",
     "description": "Kansas Open Records Act exemption: Law Enforcement Records"},
    {"category": "KS ORA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Kansas Open Records Act exemption: Personnel Records"},
    {"category": "KS ORA - Attorney-Client", "rule_type": "keyword",
     "definition": "attorney-client,legal privilege,work product,legal opinion,attorney advice",
     "description": "Kansas Open Records Act exemption: Attorney-Client Privilege"},
]

# Kentucky Open Records Act
KENTUCKY_RULES = [
    {"category": "KY ORA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement record",
     "description": "Kentucky Open Records Act exemption: Law Enforcement Records"},
    {"category": "KY ORA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination,preliminary",
     "description": "Kentucky Open Records Act exemption: Personnel Records"},
    {"category": "KY ORA - Attorney-Client", "rule_type": "keyword",
     "definition": "attorney-client,legal privilege,work product,legal opinion,attorney advice,privileged communication",
     "description": "Kentucky Open Records Act exemption: Attorney-Client Privilege"},
]

# Louisiana Public Records Act
LOUISIANA_RULES = [
    {"category": "LA PRA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,pending investigation",
     "description": "Louisiana Public Records Act exemption: Law Enforcement Records"},
    {"category": "LA PRA - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Louisiana Public Records Act exemption: Trade Secrets"},
    {"category": "LA PRA - Deliberative Process", "rule_type": "keyword",
     "definition": "draft recommendation,preliminary analysis,internal deliberation,policy discussion,predecisional",
     "description": "Louisiana Public Records Act exemption: Deliberative Process"},
]

# Maine FOIA
MAINE_RULES = [
    {"category": "ME FOIA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "Maine FOIA exemption: Law Enforcement Records"},
    {"category": "ME FOIA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Maine FOIA exemption: Personnel Records"},
    {"category": "ME FOIA - Medical Records", "rule_type": "keyword",
     "definition": "medical record,patient,diagnosis,treatment plan,HIPAA,health information",
     "description": "Maine FOIA exemption: Medical Records"},
]

# Maryland Public Information Act
MARYLAND_RULES = [
    {"category": "MD PIA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement record",
     "description": "Maryland Public Information Act exemption: Law Enforcement Records"},
    {"category": "MD PIA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Maryland Public Information Act exemption: Personnel Records"},
    {"category": "MD PIA - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Maryland Public Information Act exemption: Trade Secrets"},
]

# Massachusetts Public Records Law
MASSACHUSETTS_RULES = [
    {"category": "MA PRL - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,investigatory material",
     "description": "Massachusetts Public Records Law exemption: Law Enforcement Records"},
    {"category": "MA PRL - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination,medical information",
     "description": "Massachusetts Public Records Law exemption: Personnel/Medical Records"},
    {"category": "MA PRL - Attorney-Client", "rule_type": "keyword",
     "definition": "attorney-client,legal privilege,work product,legal opinion,attorney advice",
     "description": "Massachusetts Public Records Law exemption: Attorney-Client Privilege"},
]

# Michigan FOIA
MICHIGAN_RULES = [
    {"category": "MI FOIA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement record",
     "description": "Michigan FOIA exemption: Law Enforcement Records"},
    {"category": "MI FOIA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Michigan FOIA exemption: Personnel Records"},
    {"category": "MI FOIA - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Michigan FOIA exemption: Trade Secrets"},
]

# Minnesota Government Data Practices Act
MINNESOTA_RULES = [
    {"category": "MN GDPA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,confidential investigative data",
     "description": "Minnesota Government Data Practices Act exemption: Law Enforcement Records"},
    {"category": "MN GDPA - Personnel Data", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination,personnel data",
     "description": "Minnesota Government Data Practices Act exemption: Personnel Data"},
    {"category": "MN GDPA - Medical Data", "rule_type": "keyword",
     "definition": "medical record,patient,diagnosis,treatment plan,HIPAA,health information,medical data",
     "description": "Minnesota Government Data Practices Act exemption: Medical Data"},
]

# Mississippi Public Records Act
MISSISSIPPI_RULES = [
    {"category": "MS PRA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "Mississippi Public Records Act exemption: Law Enforcement Records"},
    {"category": "MS PRA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Mississippi Public Records Act exemption: Personnel Records"},
    {"category": "MS PRA - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Mississippi Public Records Act exemption: Trade Secrets"},
]

# Missouri Sunshine Law
MISSOURI_RULES = [
    {"category": "MO SL - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement record",
     "description": "Missouri Sunshine Law exemption: Law Enforcement Records"},
    {"category": "MO SL - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Missouri Sunshine Law exemption: Personnel Records"},
    {"category": "MO SL - Attorney-Client", "rule_type": "keyword",
     "definition": "attorney-client,legal privilege,work product,legal opinion,attorney advice,privileged communication",
     "description": "Missouri Sunshine Law exemption: Attorney-Client Privilege"},
]

# Montana Right to Know
MONTANA_RULES = [
    {"category": "MT RTK - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "Montana Right to Know exemption: Law Enforcement Records"},
    {"category": "MT RTK - Personal Privacy", "rule_type": "keyword",
     "definition": "personal information,home address,financial record,private information,individual privacy",
     "description": "Montana Right to Know exemption: Personal Privacy"},
    {"category": "MT RTK - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Montana Right to Know exemption: Trade Secrets"},
]

# Nebraska Public Records Statutes
NEBRASKA_RULES = [
    {"category": "NE PRS - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "Nebraska Public Records Statutes exemption: Law Enforcement Records"},
    {"category": "NE PRS - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Nebraska Public Records Statutes exemption: Personnel Records"},
    {"category": "NE PRS - Medical Records", "rule_type": "keyword",
     "definition": "medical record,patient,diagnosis,treatment plan,HIPAA,health information",
     "description": "Nebraska Public Records Statutes exemption: Medical Records"},
]

# Nevada Public Records Act
NEVADA_RULES = [
    {"category": "NV PRA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement record",
     "description": "Nevada Public Records Act exemption: Law Enforcement Records"},
    {"category": "NV PRA - Personal Privacy", "rule_type": "keyword",
     "definition": "personal information,home address,financial record,private information,unwarranted invasion of privacy",
     "description": "Nevada Public Records Act exemption: Personal Privacy"},
    {"category": "NV PRA - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Nevada Public Records Act exemption: Trade Secrets"},
]

# New Hampshire Right-to-Know Law
NEW_HAMPSHIRE_RULES = [
    {"category": "NH RTK - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "New Hampshire Right-to-Know Law exemption: Law Enforcement Records"},
    {"category": "NH RTK - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination,internal personnel",
     "description": "New Hampshire Right-to-Know Law exemption: Personnel Records"},
    {"category": "NH RTK - Attorney-Client", "rule_type": "keyword",
     "definition": "attorney-client,legal privilege,work product,legal opinion,attorney advice",
     "description": "New Hampshire Right-to-Know Law exemption: Attorney-Client Privilege"},
]

# New Jersey OPRA
NEW_JERSEY_RULES = [
    {"category": "NJ OPRA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement record",
     "description": "New Jersey OPRA exemption: Law Enforcement Records"},
    {"category": "NJ OPRA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "New Jersey OPRA exemption: Personnel Records"},
    {"category": "NJ OPRA - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "New Jersey OPRA exemption: Trade Secrets"},
]

# New Mexico Inspection of Public Records Act
NEW_MEXICO_RULES = [
    {"category": "NM IPRA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "New Mexico Inspection of Public Records Act exemption: Law Enforcement Records"},
    {"category": "NM IPRA - Medical Records", "rule_type": "keyword",
     "definition": "medical record,patient,diagnosis,treatment plan,HIPAA,health information",
     "description": "New Mexico Inspection of Public Records Act exemption: Medical Records"},
    {"category": "NM IPRA - Attorney-Client", "rule_type": "keyword",
     "definition": "attorney-client,legal privilege,work product,legal opinion,attorney advice",
     "description": "New Mexico Inspection of Public Records Act exemption: Attorney-Client Privilege"},
]

# North Carolina Public Records Law
NORTH_CAROLINA_RULES = [
    {"category": "NC PRL - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,criminal investigation",
     "description": "North Carolina Public Records Law exemption: Law Enforcement Records"},
    {"category": "NC PRL - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "North Carolina Public Records Law exemption: Personnel Records"},
    {"category": "NC PRL - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "North Carolina Public Records Law exemption: Trade Secrets"},
]

# North Dakota Open Records
NORTH_DAKOTA_RULES = [
    {"category": "ND OR - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,active investigation",
     "description": "North Dakota Open Records exemption: Law Enforcement Records"},
    {"category": "ND OR - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "North Dakota Open Records exemption: Personnel Records"},
    {"category": "ND OR - Medical Records", "rule_type": "keyword",
     "definition": "medical record,patient,diagnosis,treatment plan,HIPAA,health information",
     "description": "North Dakota Open Records exemption: Medical Records"},
]

# Ohio Public Records Act
OHIO_RULES = [
    {"category": "OH PRA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,confidential law enforcement",
     "description": "Ohio Public Records Act exemption: Law Enforcement Records"},
    {"category": "OH PRA - Medical Records", "rule_type": "keyword",
     "definition": "medical record,patient,diagnosis,treatment plan,HIPAA,health information",
     "description": "Ohio Public Records Act exemption: Medical Records"},
    {"category": "OH PRA - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Ohio Public Records Act exemption: Trade Secrets"},
]

# Oklahoma Open Records Act
OKLAHOMA_RULES = [
    {"category": "OK ORA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "Oklahoma Open Records Act exemption: Law Enforcement Records"},
    {"category": "OK ORA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Oklahoma Open Records Act exemption: Personnel Records"},
    {"category": "OK ORA - Personal Privacy", "rule_type": "keyword",
     "definition": "personal information,home address,financial record,private information",
     "description": "Oklahoma Open Records Act exemption: Personal Privacy"},
]

# Oregon Public Records Law
OREGON_RULES = [
    {"category": "OR PRL - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,investigatory information",
     "description": "Oregon Public Records Law exemption: Law Enforcement Records"},
    {"category": "OR PRL - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Oregon Public Records Law exemption: Trade Secrets"},
    {"category": "OR PRL - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Oregon Public Records Law exemption: Personnel Records"},
]

# Pennsylvania Right-to-Know Law
PENNSYLVANIA_RULES = [
    {"category": "PA RTKL - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,criminal investigative record",
     "description": "Pennsylvania Right-to-Know Law exemption: Law Enforcement Records"},
    {"category": "PA RTKL - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Pennsylvania Right-to-Know Law exemption: Trade Secrets"},
    {"category": "PA RTKL - Personal Security", "rule_type": "keyword",
     "definition": "personal information,home address,social security,personal security,employee home address",
     "description": "Pennsylvania Right-to-Know Law exemption: Personal Security"},
]

# Rhode Island Access to Public Records Act
RHODE_ISLAND_RULES = [
    {"category": "RI APRA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement record",
     "description": "Rhode Island Access to Public Records Act exemption: Law Enforcement Records"},
    {"category": "RI APRA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Rhode Island Access to Public Records Act exemption: Personnel Records"},
    {"category": "RI APRA - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Rhode Island Access to Public Records Act exemption: Trade Secrets"},
]

# South Carolina FOIA
SOUTH_CAROLINA_RULES = [
    {"category": "SC FOIA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "South Carolina FOIA exemption: Law Enforcement Records"},
    {"category": "SC FOIA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "South Carolina FOIA exemption: Personnel Records"},
    {"category": "SC FOIA - Attorney-Client", "rule_type": "keyword",
     "definition": "attorney-client,legal privilege,work product,legal opinion,attorney advice",
     "description": "South Carolina FOIA exemption: Attorney-Client Privilege"},
]

# South Dakota Open Records
SOUTH_DAKOTA_RULES = [
    {"category": "SD OR - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "South Dakota Open Records exemption: Law Enforcement Records"},
    {"category": "SD OR - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "South Dakota Open Records exemption: Personnel Records"},
    {"category": "SD OR - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "South Dakota Open Records exemption: Trade Secrets"},
]

# Tennessee Public Records Act
TENNESSEE_RULES = [
    {"category": "TN PRA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,pending investigation",
     "description": "Tennessee Public Records Act exemption: Law Enforcement Records"},
    {"category": "TN PRA - Medical Records", "rule_type": "keyword",
     "definition": "medical record,patient,diagnosis,treatment plan,HIPAA,health information",
     "description": "Tennessee Public Records Act exemption: Medical Records"},
    {"category": "TN PRA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Tennessee Public Records Act exemption: Personnel Records"},
]

# Utah GRAMA (Government Records Access and Management Act)
UTAH_RULES = [
    {"category": "UT GRAMA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,controlled classification",
     "description": "Utah GRAMA exemption: Law Enforcement Records"},
    {"category": "UT GRAMA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Utah GRAMA exemption: Personnel Records"},
    {"category": "UT GRAMA - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Utah GRAMA exemption: Trade Secrets"},
]

# Vermont Public Records Act
VERMONT_RULES = [
    {"category": "VT PRA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "Vermont Public Records Act exemption: Law Enforcement Records"},
    {"category": "VT PRA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Vermont Public Records Act exemption: Personnel Records"},
    {"category": "VT PRA - Personal Privacy", "rule_type": "keyword",
     "definition": "personal information,home address,financial record,private information,individual privacy",
     "description": "Vermont Public Records Act exemption: Personal Privacy"},
]

# Virginia FOIA
VIRGINIA_RULES = [
    {"category": "VA FOIA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement record",
     "description": "Virginia FOIA exemption: Law Enforcement Records"},
    {"category": "VA FOIA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Virginia FOIA exemption: Personnel Records"},
    {"category": "VA FOIA - Attorney-Client", "rule_type": "keyword",
     "definition": "attorney-client,legal privilege,work product,legal opinion,attorney advice,privileged communication",
     "description": "Virginia FOIA exemption: Attorney-Client Privilege"},
]

# Washington Public Records Act
WASHINGTON_RULES = [
    {"category": "WA PRA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement record",
     "description": "Washington Public Records Act exemption: Law Enforcement Records"},
    {"category": "WA PRA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Washington Public Records Act exemption: Personnel Records"},
    {"category": "WA PRA - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information,valuable formula",
     "description": "Washington Public Records Act exemption: Trade Secrets"},
]

# West Virginia FOIA
WEST_VIRGINIA_RULES = [
    {"category": "WV FOIA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "West Virginia FOIA exemption: Law Enforcement Records"},
    {"category": "WV FOIA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "West Virginia FOIA exemption: Personnel Records"},
    {"category": "WV FOIA - Medical Records", "rule_type": "keyword",
     "definition": "medical record,patient,diagnosis,treatment plan,HIPAA,health information",
     "description": "West Virginia FOIA exemption: Medical Records"},
]

# Wisconsin Open Records Law
WISCONSIN_RULES = [
    {"category": "WI ORL - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence,law enforcement record",
     "description": "Wisconsin Open Records Law exemption: Law Enforcement Records"},
    {"category": "WI ORL - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Wisconsin Open Records Law exemption: Personnel Records"},
    {"category": "WI ORL - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Wisconsin Open Records Law exemption: Trade Secrets"},
]

# Wyoming Public Records Act
WYOMING_RULES = [
    {"category": "WY PRA - Law Enforcement", "rule_type": "keyword",
     "definition": "investigation,informant,undercover,surveillance,criminal intelligence",
     "description": "Wyoming Public Records Act exemption: Law Enforcement Records"},
    {"category": "WY PRA - Personnel Records", "rule_type": "keyword",
     "definition": "personnel file,employee evaluation,disciplinary action,performance review,termination",
     "description": "Wyoming Public Records Act exemption: Personnel Records"},
    {"category": "WY PRA - Trade Secrets", "rule_type": "keyword",
     "definition": "trade secret,proprietary,confidential business,competitive advantage,commercial information",
     "description": "Wyoming Public Records Act exemption: Trade Secrets"},
]

# Universal PII regex rules (apply to all jurisdictions)
UNIVERSAL_PII_RULES = [
    {"state_code": "ALL", "category": "pii_ssn", "rule_type": "regex",
     "rule_definition": r"\b\d{3}-\d{2}-\d{4}\b",
     "description": "Social Security Number pattern"},
    {"state_code": "ALL", "category": "pii_phone", "rule_type": "regex",
     "rule_definition": r"\b\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
     "description": "US phone number pattern"},
    {"state_code": "ALL", "category": "pii_email", "rule_type": "regex",
     "rule_definition": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
     "description": "Email address pattern"},
    {"state_code": "ALL", "category": "pii_credit_card", "rule_type": "regex",
     "rule_definition": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
     "description": "Credit card number pattern"},
    {"state_code": "ALL", "category": "pii_dob", "rule_type": "regex",
     "rule_definition": r"\b(?:0[1-9]|1[0-2])[/\-](?:0[1-9]|[12]\d|3[01])[/\-](?:19|20)\d{2}\b",
     "description": "Date of birth pattern (MM/DD/YYYY or MM-DD-YYYY)"},
]

# Registry mapping state code -> (rules list, law name, display name)
STATE_RULES_REGISTRY = [
    ("CO", COLORADO_CORA_RULES, "CORA", "Colorado"),
    ("TX", TEXAS_TPIA_RULES, "TPIA", "Texas"),
    ("CA", CALIFORNIA_CPRA_RULES, "CPRA", "California"),
    ("NY", NEW_YORK_FOIL_RULES, "FOIL", "New York"),
    ("FL", FLORIDA_PRA_RULES, "FL PRA", "Florida"),
    ("AL", ALABAMA_RULES, "AL ORA", "Alabama"),
    ("AK", ALASKA_RULES, "AK PRA", "Alaska"),
    ("AZ", ARIZONA_RULES, "AZ PRL", "Arizona"),
    ("AR", ARKANSAS_RULES, "AR FOIA", "Arkansas"),
    ("CT", CONNECTICUT_RULES, "CT FOIA", "Connecticut"),
    ("DE", DELAWARE_RULES, "DE FOIA", "Delaware"),
    ("DC", DC_RULES, "DC FOIA", "District of Columbia"),
    ("GA", GEORGIA_RULES, "GA ORA", "Georgia"),
    ("HI", HAWAII_RULES, "HI UIPA", "Hawaii"),
    ("ID", IDAHO_RULES, "ID PRA", "Idaho"),
    ("IL", ILLINOIS_RULES, "IL FOIA", "Illinois"),
    ("IN", INDIANA_RULES, "IN APRA", "Indiana"),
    ("IA", IOWA_RULES, "IA ORA", "Iowa"),
    ("KS", KANSAS_RULES, "KS ORA", "Kansas"),
    ("KY", KENTUCKY_RULES, "KY ORA", "Kentucky"),
    ("LA", LOUISIANA_RULES, "LA PRA", "Louisiana"),
    ("ME", MAINE_RULES, "ME FOIA", "Maine"),
    ("MD", MARYLAND_RULES, "MD PIA", "Maryland"),
    ("MA", MASSACHUSETTS_RULES, "MA PRL", "Massachusetts"),
    ("MI", MICHIGAN_RULES, "MI FOIA", "Michigan"),
    ("MN", MINNESOTA_RULES, "MN GDPA", "Minnesota"),
    ("MS", MISSISSIPPI_RULES, "MS PRA", "Mississippi"),
    ("MO", MISSOURI_RULES, "MO SL", "Missouri"),
    ("MT", MONTANA_RULES, "MT RTK", "Montana"),
    ("NE", NEBRASKA_RULES, "NE PRS", "Nebraska"),
    ("NV", NEVADA_RULES, "NV PRA", "Nevada"),
    ("NH", NEW_HAMPSHIRE_RULES, "NH RTK", "New Hampshire"),
    ("NJ", NEW_JERSEY_RULES, "NJ OPRA", "New Jersey"),
    ("NM", NEW_MEXICO_RULES, "NM IPRA", "New Mexico"),
    ("NC", NORTH_CAROLINA_RULES, "NC PRL", "North Carolina"),
    ("ND", NORTH_DAKOTA_RULES, "ND OR", "North Dakota"),
    ("OH", OHIO_RULES, "OH PRA", "Ohio"),
    ("OK", OKLAHOMA_RULES, "OK ORA", "Oklahoma"),
    ("OR", OREGON_RULES, "OR PRL", "Oregon"),
    ("PA", PENNSYLVANIA_RULES, "PA RTKL", "Pennsylvania"),
    ("RI", RHODE_ISLAND_RULES, "RI APRA", "Rhode Island"),
    ("SC", SOUTH_CAROLINA_RULES, "SC FOIA", "South Carolina"),
    ("SD", SOUTH_DAKOTA_RULES, "SD OR", "South Dakota"),
    ("TN", TENNESSEE_RULES, "TN PRA", "Tennessee"),
    ("UT", UTAH_RULES, "UT GRAMA", "Utah"),
    ("VT", VERMONT_RULES, "VT PRA", "Vermont"),
    ("VA", VIRGINIA_RULES, "VA FOIA", "Virginia"),
    ("WA", WASHINGTON_RULES, "WA PRA", "Washington"),
    ("WV", WEST_VIRGINIA_RULES, "WV FOIA", "West Virginia"),
    ("WI", WISCONSIN_RULES, "WI ORL", "Wisconsin"),
    ("WY", WYOMING_RULES, "WY PRA", "Wyoming"),
]


def _build_rules_list():
    """Build a flat RULES list for direct import by tests and other consumers."""
    rules = []
    for state_code, state_rules, law_name, state_name in STATE_RULES_REGISTRY:
        for rule_data in state_rules:
            description = rule_data.get(
                "description",
                f"{state_name} {law_name} exemption: {rule_data['category'].replace(f'{law_name} - ', '')}",
            )
            rules.append({
                "state_code": state_code,
                "category": rule_data["category"],
                "rule_type": "keyword",
                "rule_definition": rule_data["definition"],
                "description": description,
            })
    # Add universal PII rules
    rules.extend(UNIVERSAL_PII_RULES)
    return rules


RULES = _build_rules_list()


async def seed_state(session, user, state_code: str, rules: list, law_name: str, state_name: str):
    created = 0
    skipped = 0
    for rule_data in rules:
        existing = await session.execute(
            select(ExemptionRule).where(
                ExemptionRule.category == rule_data["category"],
                ExemptionRule.state_code == state_code,
            )
        )
        if existing.scalar_one_or_none():
            print(f"  Skipped (exists): {rule_data['category']}")
            skipped += 1
            continue

        description = rule_data.get(
            "description",
            f"{state_name} {law_name} exemption: {rule_data['category'].replace(f'{law_name} - ', '')}",
        )
        rule = ExemptionRule(
            state_code=state_code,
            category=rule_data["category"],
            rule_type=RuleType.KEYWORD,
            rule_definition=rule_data["definition"],
            description=description,
            enabled=True,
            created_by=user.id,
        )
        session.add(rule)
        print(f"  Created: {rule_data['category']}")
        created += 1

    return created, skipped


async def seed():
    async with async_session_maker() as session:
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if not user:
            print("No users in database. Run the application first.")
            return

        total_created = 0
        for state_code, rules, law_name, state_name in STATE_RULES_REGISTRY:
            print(f"\n--- {state_name} ({state_code}) {law_name} ---")
            created, skipped = await seed_state(session, user, state_code, rules, law_name, state_name)
            total_created += created
            print(f"  {created} created, {skipped} skipped")

        await session.commit()
        print(f"\nTotal rules seeded: {total_created}")


if __name__ == "__main__":
    asyncio.run(seed())
