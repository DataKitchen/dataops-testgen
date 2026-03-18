"""HTML login page for the OAuth authorization code flow.

Served when an MCP client (or any OAuth client) redirects the user to
/oauth/authorize. The user enters their TestGen credentials, which are
posted back to /oauth/authorize to complete the flow.
"""

from html import escape


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
    authorize_label = f"Authorize <strong>{client_display}</strong> to access TestGen on your behalf"

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
        .logo {{
            font-size: 22px;
            font-weight: 700;
            margin-bottom: 4px;
            color: var(--primary);
        }}
        .subtitle {{
            font-size: 14px;
            color: var(--text-secondary);
            margin-bottom: 24px;
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
    <div class="card">
        <div class="logo">TestGen</div>
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
