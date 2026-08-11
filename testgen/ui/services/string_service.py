def snake_case_to_title_case(snake_case):
    words = snake_case.split("_")
    title_case_words = [word.capitalize() for word in words]
    title_case = " ".join(title_case_words)
    return title_case
