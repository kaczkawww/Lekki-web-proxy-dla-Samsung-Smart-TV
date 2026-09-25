import reflex as rx

from app.terminal_server import server


def terminal_url() -> str:
    return f"{rx.config.get_config().api_url.rstrip('/')}/terminal/"


def index() -> rx.Component:
    return rx.el.main(
        rx.el.iframe(
            src=terminal_url(),
            title="ORSAY — terminal internetowy",
            class_name="block h-dvh w-full border-0 bg-[#0b121c] text-white",
        ),
        class_name="h-dvh w-full overflow-hidden bg-[#0b121c] text-white font-[Arial]",
    )


app = rx.App(
    theme=rx.theme(appearance="light"),
    api_transformer=server,
)
app.add_page(index, route="/", title="ORSAY — terminal internetowy")
