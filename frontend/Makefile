.PHONY: setup dev lint typecheck check

setup:
	npm install

dev:
	npx vite

lint:
	npx eslint . --max-warnings 0

typecheck:
	npx tsc -b

# lint + typecheck + production build, run before pushing
check: lint typecheck
	npx vite build
