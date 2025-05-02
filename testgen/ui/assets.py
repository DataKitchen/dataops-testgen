import pathlib

from streamlit.elements.lib.image_utils import WidthBehavior, image_to_url


def get_asset_path(path: str) -> str:
    return (pathlib.Path(__file__).parent / "assets" / path).as_posix()


def get_asset_data_url(path: str) -> str:
    absolute_path = get_asset_path(path)
    return image_to_url(
        absolute_path,
        int(WidthBehavior.ORIGINAL),
        clamp=False,
        channels="RGB",
        output_format="auto",
        image_id=path,
    )
