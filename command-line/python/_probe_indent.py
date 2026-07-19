import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")  
lines = open("ue58_core.py", "r", encoding="utf-8").readlines()
for i in range(396, min(445, len(lines))):
    ln = lines[i].rstrip()
    if ln:
        print(f"{i+1}: {ln}")
