.PHONY: install run test demo docker-build docker-up

install:
	pip install -r requirements.txt

run:
	streamlit run app.py

demo:
	DEMO_MODE=true streamlit run app.py

test:
	pytest -q

docker-build:
	docker build -t naijagreen-chat .

docker-up:
	docker compose up --build
