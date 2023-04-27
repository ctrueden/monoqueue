help:
	@echo "Available targets:\n\
		clean - remove build files and directories\n\
		test  - run automated test suite\n\
		dist  - generate release archives"

clean:
	bin/clean.sh

test:
	bin/test.sh

dist: clean
	python -m build

.PHONY: test
