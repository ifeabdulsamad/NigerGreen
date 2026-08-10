python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

Then launch in demo mode (no API key needed — built-in rule engine answers questions):

DEMO_MODE=true streamlit run app.py

Open http://localhost:8501 in your browser. Upload data/emissions_lagos.csv in the sidebar and try asking "total co2 emissions per year" or "average co2 emissions".

For the real LLM pipeline instead of demo mode: get a free key at console.groq.com, then:

cp .env.example .env
edit .env, put your key in GROQ_API_KEY=
streamlit run app.py

Want me to run the test suite inside the sandbox first to confirm everything still passes before you fire it up?
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
Shutting down… (finalizing session)
