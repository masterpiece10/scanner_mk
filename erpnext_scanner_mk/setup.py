#!/usr/bin/env python3

from setuptools import setup, find_packages

setup(
	name="scanner_mk",
	version="1.0.0",
	description="ERPNext Scanner MK - Automatic invoice recognition and processing",
	author="Tik13 GmbH",
	author_email="mike@tik13.org",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=[
		"requests>=2.25.0",
		"rapidfuzz>=2.0.0",
		"Pillow>=8.0.0",
		"pytesseract>=0.3.8",
		"pdf2image>=1.16.0",
	],
	python_requires=">=3.8",
	classifiers=[
		"Development Status :: 4 - Beta",
		"Intended Audience :: Developers",
		"License :: OSI Approved :: MIT License",
		"Programming Language :: Python :: 3",
		"Programming Language :: Python :: 3.8",
		"Programming Language :: Python :: 3.9",
		"Programming Language :: Python :: 3.10",
		"Programming Language :: Python :: 3.11",
	],
	keywords="erpnext invoice scanner ocr ai",
	license="MIT",
)
