.PHONY: clean install editable

clean:
	rm -rf build/
	rm -rf dist/
	find . -name '*.egg-info' -exec rm -rf {} +
	find . -name '__pycache__' -exec rm -rf {} +
	find . -name '*.pyc' -delete

editable:
	python -m pip install -e .

install:
	python -m pip install .