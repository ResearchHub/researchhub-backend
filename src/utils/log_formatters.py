from pythonjsonlogger.json import JsonFormatter


class UvicornAccessJsonFormatter(JsonFormatter):
    """
    JSON formatter for `uvicorn.access` records.
    Exposes the request details as Datadog standard attributes.
    """

    def add_fields(self, log_data, record, message_dict):
        super().add_fields(log_data, record, message_dict)

        # uvicorn logs: client_addr, method, path, http_version, status_code
        if not isinstance(record.args, tuple) or len(record.args) != 5:
            return

        client_addr, method, path, http_version, status_code = record.args
        log_data["http"] = {
            "method": method,
            "url": path,
            "version": http_version,
            "status_code": status_code,
        }
        log_data["network"] = {"client": {"ip": client_addr.rpartition(":")[0]}}
