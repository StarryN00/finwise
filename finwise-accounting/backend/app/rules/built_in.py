BUILT_IN_RULES = [
    {"keywords": ["手续费"], "business_type": "BANK_FEE", "line_label": "银行手续费", "direction": "EXPENSE"},
    {"keywords": ["增值税", "税款", "税费"], "business_type": "TAX_PAYMENT", "line_label": "税费缴纳", "direction": "TAX"},
    {"keywords": ["工资", "薪资"], "business_type": "SALARY", "line_label": "工资薪金", "direction": "EXPENSE"},
    {"keywords": ["社保"], "business_type": "SOCIAL_INSURANCE", "line_label": "社保缴纳", "direction": "EXPENSE"},
    {"keywords": ["公积金"], "business_type": "HOUSING_FUND", "line_label": "公积金缴纳", "direction": "EXPENSE"},
    {"keywords": ["利息"], "business_type": "INTEREST", "line_label": "利息收支", "direction": "NON_OPERATING"},
    {"keywords": ["股东"], "business_type": "SHAREHOLDER_TRANSFER", "line_label": "股东往来", "direction": "NON_OPERATING"},
    {"keywords": ["服务费"], "business_type": "SERVICE_FEE", "line_label": "服务费", "direction": "EXPENSE"},
]
