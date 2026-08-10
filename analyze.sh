#!/bin/bash
# save as analyze.sh and run: bash analyze.sh

echo "=== DIRECTORY TREE ===" > codebase_overview.txt
tree -I 'venv|__pycache__|.git|*.pyc' --dirsfirst >> codebase_overview.txt

echo -e "\n\n=== ENTRY POINTS ===" >> codebase_overview.txt
grep -rn "if __name__\|def main\|uvicorn\|\.run(" --include="*.py" . >> codebase_overview.txt

echo -e "\n\n=== ALL IMPORTS ===" >> codebase_overview.txt
grep -rn "^from\|^import" --include="*.py" . >> codebase_overview.txt

echo -e "\n\n=== CLASSES & FUNCTIONS ===" >> codebase_overview.txt
grep -rn "def \|class " --include="*.py" . >> codebase_overview.txt

echo "Done! Open codebase_overview.txt"

