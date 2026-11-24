"""Stable document-wide numbering for review images."""


def count_review_images(pages: list[dict]) -> int:
    return sum(
        len(page.get("images", []))
        for page in pages
    )


def assign_review_image_numbers(
    pages: list[dict],
    *,
    previous_count: int = 0,
) -> int:
    """Assign image ordinals in page and extraction order.

    Mutates review image dictionaries in place and returns the
    cumulative image count, ready for the next processing chunk.

    Images without previews are included in the sequence.
    """
    image_count = previous_count

    for page in sorted(
        pages,
        key=lambda page: page["pageNumber"],
    ):
        for image in page.get("images", []):
            image_count += 1
            image["imageNumber"] = image_count

    return image_count
