"""Console entrypoint for the Mikro-Clear Web panel."""

import uvicorn

from mikroclear.web.app import create_app
from mikroclear.web.config import WebSettings


def main() -> None:
    settings = WebSettings.from_env()
    settings.validate()
    uvicorn.run(
        create_app(web_settings=settings),
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )


if __name__ == "__main__":
    main()
