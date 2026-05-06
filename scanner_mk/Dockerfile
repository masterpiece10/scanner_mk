FROM frappe/frappe_docker:latest

WORKDIR /frappe

COPY . /frappe

# Install the custom app
COPY . /frappe/apps/erpnext_scanner_mk
RUN cd /frappe/apps/erpnext_scanner_mk && frappe build && frappe install-app erpnext_scanner_mk

CMD ["sh", "-c", "bench serve --no-auto restart"]