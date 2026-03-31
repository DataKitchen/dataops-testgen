"""HTML login page for the OAuth authorization code flow.

Served when an MCP client (or any OAuth client) redirects the user to
/oauth/authorize. The user enters their TestGen credentials, which are
posted back to /oauth/authorize to complete the flow.
"""

from html import escape

# Inline SVG of the DataKitchen icon (from testgen/ui/assets/dk_icon.svg).
# Hardcoded for now — custom logo plugin support to be added later.
_DK_ICON_SVG = """\
<svg width="80" height="89" viewBox="0 0 80 89" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M67.4861 43.9053C67.4861 42.3664 67.3948 40.918 67.2121 39.4695C66.6642 32.4085 64.9291 26.0716 61.8242 20.64C58.7193 15.1179 54.6098 10.7726 49.4959 7.42315C48.4 6.69894 47.3955 5.97473 46.2083 5.43157C43.7427 4.1642 41.1857 3.16841 38.4461 2.35367L0 44.2674L38.5374 86.2718C41.1857 85.457 43.834 84.4612 46.2997 83.1938C47.1215 82.7412 47.9434 82.1981 48.7653 81.6549C54.2446 78.2149 58.7193 73.6886 61.9155 67.8949C65.2031 62.1012 66.9382 55.3117 67.3034 47.6169C67.3948 46.8022 67.3948 45.9875 67.3948 45.1727C67.3948 44.8106 67.4861 44.539 67.4861 44.1769C67.4861 44.0864 67.4861 44.0864 67.4861 43.9959C67.3948 44.0864 67.4861 43.9959 67.4861 43.9053Z" fill="#AAD046"/>
<path d="M38.4461 2.26316C34.2453 0.995792 29.6793 0.271579 24.8393 0.090526C22.8302 0.090526 20.7298 0 18.5381 0H4.3834C1.91774 0 0 1.99158 0 4.34527V31.3222V44.2675L38.4461 2.26316Z" fill="#06A04A"/>
<path d="M0 57.2127V84.1896C0 86.6338 2.00906 88.5349 4.3834 88.5349H18.5381C20.7298 88.5349 22.8302 88.5349 24.8393 88.4443C29.6793 88.3538 34.2453 87.5391 38.4461 86.2717L0 44.2674V57.2127Z" fill="#06A04A"/>
<path d="M75.6136 0.0905151H52.6007C52.8747 0.271568 53.0573 0.452622 53.3313 0.724201C59.1758 4.70737 64.0158 9.77685 67.5774 16.2042C71.2302 22.7221 73.3306 30.2358 73.9698 38.6548C74.1525 40.3748 74.2438 42.1853 74.2438 43.9959C74.2438 44.0864 74.2438 44.1769 74.2438 44.2675C74.2438 44.358 74.2438 44.358 74.2438 44.4485C74.2438 44.8106 74.1525 45.1727 74.1525 45.6254C74.1525 46.6211 74.0611 47.5264 73.9698 48.5222C73.5132 57.6654 71.4128 65.7222 67.486 72.6928C63.7419 79.3917 58.6279 84.6423 52.4181 88.6254V88.716H75.6136C78.0793 88.716 79.997 86.7244 79.997 84.3707V4.70737C80.0883 2.0821 78.0793 0.0905151 75.6136 0.0905151Z" fill="#AAD046"/>
</svg>"""


def render_login_page(
    client_id: str,
    redirect_uri: str,
    response_type: str,
    scope: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    error: str = "",
    client_name: str = "",
) -> str:
    error_html = (
        f'<div class="error">{escape(error)}</div>' if error else ""
    )
    client_display = escape(client_name) if client_name else escape(client_id)
    authorize_label = f"By signing in, <strong>{client_display}</strong> will be authorized to access TestGen on your behalf."

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TestGen — Sign In</title>
    <style>
        :root {{
            --bg: #f5f5f5;
            --card-bg: #ffffff;
            --text: #1a1a1a;
            --text-secondary: #555;
            --border: #ddd;
            --primary: #06a04a;
            --primary-hover: #058a3f;
            --error: #EF5350;
            --shadow: rgba(0, 0, 0, 0.1);
        }}
        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg: #1a1a2e;
                --card-bg: #24243e;
                --text: #e0e0e0;
                --text-secondary: #aaa;
                --border: #444;
                --shadow: rgba(0, 0, 0, 0.4);
            }}
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }}
        .card {{
            background: var(--card-bg);
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 12px var(--shadow);
            width: 100%;
            max-width: 420px;
        }}
        .page-logo {{
            position: fixed;
            top: 20px;
            left: 20px;
        }}
        .page-logo svg {{
            width: 22px;
            height: auto;
        }}
        .card-title {{
            font-size: 22px;
            font-weight: 700;
            color: var(--primary);
        }}
        .subtitle {{
            font-size: 14px;
            color: var(--text-secondary);
            margin: 24px 0;
            line-height: 1.4;
        }}
        .error {{
            background: color-mix(in srgb, var(--error) 10%, transparent);
            color: var(--error);
            padding: 10px 14px;
            border-radius: 4px;
            font-size: 13px;
            margin-bottom: 16px;
        }}
        label {{
            display: block;
            font-size: 13px;
            font-weight: 500;
            margin-bottom: 4px;
            color: var(--text-secondary);
        }}
        input[type=text], input[type=password] {{
            width: 100%;
            padding: 10px 12px;
            border: 1px solid var(--border);
            border-radius: 4px;
            font-size: 14px;
            margin-bottom: 16px;
            background: var(--card-bg);
            color: var(--text);
        }}
        input:focus {{
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary) 20%, transparent);
        }}
        button {{
            margin-top: 12px;
            width: 100%;
            padding: 12px;
            background: var(--primary);
            color: #fff;
            border: none;
            border-radius: 4px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
        }}
        button:hover {{
            background: var(--primary-hover);
        }}
    </style>
</head>
<body>
    <div class="page-logo">{_DK_ICON_SVG}</div>
    <div class="card">
        <div class="card-title">DataKitchen DataOps TestGen</div>
        <p class="subtitle">{authorize_label}</p>
        {error_html}
        <form method="POST" action="/oauth/authorize">
            <input type="hidden" name="client_id" value="{escape(client_id)}">
            <input type="hidden" name="redirect_uri" value="{escape(redirect_uri)}">
            <input type="hidden" name="response_type" value="{escape(response_type)}">
            <input type="hidden" name="scope" value="{escape(scope)}">
            <input type="hidden" name="state" value="{escape(state)}">
            <input type="hidden" name="code_challenge" value="{escape(code_challenge)}">
            <input type="hidden" name="code_challenge_method" value="{escape(code_challenge_method)}">
            <label for="username">Username</label>
            <input type="text" id="username" name="username" required autofocus>
            <label for="password">Password</label>
            <input type="password" id="password" name="password" required>
            <button type="submit">Sign In</button>
        </form>
    </div>
</body>
</html>"""
