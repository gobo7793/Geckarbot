# Install sphinx
#pip3 install sphinx

# refresh source files
mv index.rst index.rst_
rm *.rst
mv index.rst_ index.rst
sphinx-apidoc -o . ..

# Build
make html
