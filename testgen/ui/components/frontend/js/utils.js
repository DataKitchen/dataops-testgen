function enforceElementWidth(
    /** @type Element */element,
    /** @type number */width,
) {
    const observer = new ResizeObserver(() => {
        element.width = width;
    });

    observer.observe(element);
}

export { enforceElementWidth };
