.PHONY: test lint run build install clean

test:
	python3 -m unittest discover -s tests -v

lint:
	python3 -m compileall -q gpufinder
	python3 scripts/check_no_secrets.py

run:
	python3 -m gpufinder serve --open

build:
	./macos/build.sh

install:
	./macos/build.sh --install

clean:
	rm -rf build dist .devhome
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete
