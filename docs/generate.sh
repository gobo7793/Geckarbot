# Install sphinx
#pip3 install sphinx

# refresh source files
rm *.rst
sphinx-apidoc -o . ..

# Build
make html
