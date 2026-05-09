FROM ubuntu:latest

WORKDIR /frappe

COPY . /frappe

COPY install_frappe_cli.sh /frappe

# Install Frappe CLI tools
RUN chmod +x /frappe/install_frappe_cli.sh && /frappe/install_frappe_cli.sh

# Install the custom app
COPY ./scanner_mk /frappe/apps/scanner_mk
RUN cd /frappe/apps/scanner_mk && frappe build && frappe install-app scanner_mk

CMD ["sh", "-c", "bench serve --no-auto restart"]