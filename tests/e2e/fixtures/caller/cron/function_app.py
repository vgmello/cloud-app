"""Stand-in Azure Functions entrypoint. The e2e suite only checks that this
directory is zipped and shipped, never that it runs."""


def main(timer):
    return "ok"
