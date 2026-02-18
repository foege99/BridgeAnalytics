import pandas as pd

f1 = r"C:\Users\Bruger\BridgeAnalytics\Henrik_Per_ANALYSE_1.xlsx"
f2 = r"C:\Users\Bruger\BridgeAnalytics\Henrik_Per_ANALYSE_2.xlsx"

xls1 = pd.ExcelFile(f1)
xls2 = pd.ExcelFile(f2)

print("Samme ark-navne?", set(xls1.sheet_names) == set(xls2.sheet_names))

for sheet in xls1.sheet_names:
    df1 = pd.read_excel(f1, sheet_name=sheet)
    df2 = pd.read_excel(f2, sheet_name=sheet)

    same = df1.equals(df2)
    print(sheet, "identisk?", same)
