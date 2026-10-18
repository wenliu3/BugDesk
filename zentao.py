"""Conservative connector for ZenTao's classic JSON interface (18.11).

Protocol checked against easysoft/zentaopms tag zentaopms_18.11, notably
module/user/{control.php,js/login.js}, module/bug/{control.php,model.php},
module/file/model.php and framework/base/{router,control}.class.php.
Company extensions still need a first real submission to verify compatibility.
No credential, cookie or response body is persisted. Large upload bodies use an
automatically removed temporary file while the request is in progress.
"""

from __future__ import annotations

import hashlib
import html
from html.parser import HTMLParser
import http.client
import http.cookiejar
import json
import mimetypes
from pathlib import Path
import re
import secrets
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request


class ConnectorError(Exception):
    def __init__(self, message, *, uncertain=False, remote_id=None,
                 remote_url="", partial=False, upload_status=None):
        super().__init__(message)
        self.uncertain = bool(uncertain)
        self.remote_id = remote_id
        self.remote_url = remote_url
        self.partial = bool(partial)
        self.upload_status = upload_status or {}


def _origin(url):
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme.lower(), parsed.hostname, parsed.port or (
        443 if parsed.scheme.lower() == "https" else 80)


class _SameOriginRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A POST is never replayed or followed. Its outcome needs inspection.
        if req.get_method() != "GET" or _origin(newurl) != _origin(req.full_url):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _FormNode:
    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.parent = tag, attrs or {}, parent
        self.children = []

    def text(self):
        # A caption never includes values from a nearby control or script.
        if self.tag in ("select", "input", "script", "style"):
            return ""
        return "".join(child if isinstance(child, str) else child.text()
                       for child in self.children)

    def selects(self):
        if self.tag == "select" and self.attrs.get("name"):
            return [self]
        return [control for child in self.children if isinstance(child, _FormNode)
                for control in child.selects()]


class _FormParser(HTMLParser):
    """Read observed controls and their local captions, without executing JS."""
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                 "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.selects = {}
        self.select = None
        self.option = None
        self.hidden = {}
        self.labels = {}
        self.label = None
        self.root = _FormNode("root")
        self.stack = [self.root]
        self.select_nodes = {}
        self.label_nodes = []
        self.disabled_option = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        node = _FormNode(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self.VOID_TAGS:
            self.stack.append(node)
        if tag == "select" and attrs.get("name"):
            self.select = attrs["name"]
            self.selects.setdefault(self.select, [])
            self.select_nodes.setdefault(self.select, []).append(node)
        elif tag == "option" and self.select:
            if self.option is not None:
                self._end_option()
            self.option = [attrs.get("value"), ""]
            self.disabled_option = "disabled" in attrs or any(
                ancestor.tag in ("select", "optgroup") and "disabled" in ancestor.attrs
                for ancestor in self.stack[:-1])
        elif tag == "label" and attrs.get("for"):
            self.label = attrs["for"]
            self.labels.setdefault(self.label, "")
            self.label_nodes.append(node)
        elif tag == "input" and attrs.get("type", "").lower() == "hidden":
            name = attrs.get("name", "")
            if re.fullmatch(r"(?:csrf[_-]?token|csrf|_token|token|uid)", name, re.I):
                self.hidden[name] = attrs.get("value", "")

    def handle_data(self, data):
        self.stack[-1].children.append(data)
        if self.option is not None:
            self.option[1] += data
        if self.label:
            self.labels[self.label] += data

    def handle_endtag(self, tag):
        if tag == "option" and self.option is not None and self.select:
            self._end_option()
        elif tag == "select":
            if self.option is not None and self.select:
                self._end_option()
            self.select = self.option = None
        elif tag == "label":
            self.label = None
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def _end_option(self):
        value, label = self.option
        if value is None:
            value = label.strip()
        if not self.disabled_option:
            self.selects[self.select].append({"value": value, "label": label.strip()})
        self.option = None
        self.disabled_option = False

    def captions(self, name):
        """Associate only explicit or immediately adjacent field captions.

        Classic forms put several fields in one row and even one input-group.
        Scanning the whole row would mistake priority/OS for probability.
        """
        result = []
        for control in self.select_nodes.get(name, []):
            if "disabled" in control.attrs:
                continue
            identifiers = {control.attrs.get("id", ""), name, name.removesuffix("[]")}
            result += [label.text() for label in self.label_nodes
                       if label.attrs.get("for") in identifiers]
            result += [control.attrs.get(key, "") for key in ("aria-label", "data-label", "title")]
            child, parent = control, control.parent
            while parent and parent.tag not in ("body", "html", "root"):
                if parent.tag == "label":
                    result.append(parent.text())
                siblings = [node for node in parent.children if isinstance(node, _FormNode)]
                previous = siblings[:siblings.index(child)]
                # Stop at the first preceding control/caption. A nested picker
                # wrapper can share the same group as OS and type controls.
                for sibling in reversed(previous):
                    if sibling.selects():
                        break
                    classes = set(sibling.attrs.get("class", "").split())
                    if (sibling.tag in ("label", "th") or "input-group-addon" in classes
                            or "control-label" in classes):
                        result.append(sibling.text())
                        break
                if parent.tag in ("td", "th"):
                    # A table heading describes its adjacent cell only when
                    # that cell has one named select, rather than an entire row.
                    if len(parent.selects()) == 1 and parent.parent:
                        cells = [node for node in parent.parent.children if isinstance(node, _FormNode)]
                        before = cells[:cells.index(parent)]
                        if before and before[-1].tag == "th":
                            result.append(before[-1].text())
                    break
                if parent.tag == "form":
                    break
                child, parent = parent, parent.parent
        return [caption.strip() for caption in result if caption.strip()]


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _probability_diagnostic(parser=None):
    """Describe picker structure without exposing page content or identities.

    This return value is transient menu metadata, never a saved report. Unknown
    captions and choice data are deliberately hidden rather than copied whole.
    """
    diagnostic = {"format": "bugdesk.probability-fields", "schema_version": 1,
                  "form_read": "parsed" if parser else "unavailable",
                  "select_count": len(parser.selects) if parser else 0, "fields": []}
    if parser is None:
        return diagnostic
    excluded = {"product", "project", "execution", "module", "openedbuild", "assignedto",
                "type", "severity", "pri", "os", "branch", "story", "task", "testtask"}
    private_name = re.compile(r"account|user|member|person|assign|owner|feedback|notify|email|mail|password|secret|token|csrf", re.I)
    aliases = {"probability", "chance", "frequency", "occurprobability", "occurrenceprobability", "browser"}
    probability_caption = re.compile(r"((?:发生|出现|复现|重现)?概率)(?:[:：*＊]|[（(][^()（）]{0,12}[)）])*\Z")
    ordinary_captions = {"浏览器", "操作系统", "发生频率", "出现频率", "复现频率", "频率"}
    probability_labels = re.compile(r"(?:必现|高|中|低|偶现|总是|经常|有时|很少|不发生|不复现|无法复现|\d{1,3}%)\Z")
    def identifier(value):
        value = str(value or "")
        return value if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}(?:\[\])?", value) and not private_name.search(value) else ""
    def choice_value(value):
        value = str(value or "")
        # Preserve numeric and common short probability codes; arbitrary values
        # might contain an account, token or another company's private text.
        if re.fullmatch(r"\d{1,12}|[A-Z][A-Z0-9_]{0,7}|always|often|sometimes|rarely|high|medium|middle|low|never", value):
            return value
        return "[已隐藏]" if value else ""
    for name, choices in parser.selects.items():
        base = name.removesuffix("[]").lower()
        if base in excluded or not identifier(name):
            continue
        captions, exact_caption = [], False
        for caption in parser.captions(name):
            caption = re.sub(r"\s+", "", caption)
            match = probability_caption.fullmatch(caption)
            if match:
                shown, exact_caption = match.group(1), True
            else:
                shown = caption if caption in ordinary_captions else "[未识别标题，已隐藏]"
            if shown not in captions:
                captions.append(shown)
        controls = parser.select_nodes.get(name, [])
        entry = {"name": name, "ids": list(dict.fromkeys(identifier(node.attrs.get("id")) for node in controls if identifier(node.attrs.get("id"))))[:4],
                 "captions": captions[:4], "disabled": bool(controls) and all("disabled" in node.attrs for node in controls)}
        if base in aliases or exact_caption:
            safe_choices = [{"value": choice_value(choice.get("value")), "label": choice["label"]}
                            for choice in choices if probability_labels.fullmatch(str(choice.get("label", "")))]
            entry.update(option_count=len(choices), choices=safe_choices[:8],
                         hidden_option_count=len(choices) - len(safe_choices),
                         choices_truncated=len(safe_choices) > 8)
        diagnostic["fields"].append(entry)
        if len(diagnostic["fields"]) >= 20:
            diagnostic["fields_truncated"] = True
            break
    return diagnostic


def _fact_text(value):
    parser = _TextParser()
    parser.feed(str(value))
    return re.sub(r"\s+", "", "".join(parser.parts))


def _options(values):
    if isinstance(values, dict):
        pairs = values.items()
    elif isinstance(values, list):
        pairs = enumerate(values)
    else:
        return []
    result = []
    for key, value in pairs:
        if isinstance(value, dict):
            key = value.get("value", value.get("id", key))
            value = value.get("label", value.get("name", value.get("title", "")))
        if value is None or not isinstance(value, (str, int, float)):
            continue
        label = html.unescape(str(value)).strip()
        if label:
            result.append({"value": str(key), "label": label})
    return result


class ZenTaoClient:
    RESPONSE_LIMIT = 16 * 1024 * 1024
    FILE_LIMIT = 500 * 1024 * 1024

    def __init__(self, url, account, password, *, timeout=35):
        try:
            parsed = urllib.parse.urlsplit(str(url).strip())
            valid = parsed.scheme in ("http", "https") and parsed.hostname
            valid = valid and not parsed.username and not parsed.password
            _ = parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise ConnectorError("请填写完整的禅道地址，例如 http://公司服务器/zentao/。")
        path = parsed.path or "/"
        if re.search(r"/(?:index\.php|[^/]+\.(?:html|json))/?$", path, re.I):
            path = path.rsplit("/", 1)[0] + "/"
        if not path.endswith("/"):
            path += "/"
        self.base_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
        self.account = str(account).strip()
        self._password = str(password)
        self.timeout = timeout
        self.connected = False
        self._route = "get"
        self._cookie_jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookie_jar), _SameOriginRedirects())
        self._forms = {}

    def _url(self, module, method, params=None, *, view="json", route=None):
        params = params or {}
        route = route or self._route
        if route == "get":
            query = {"m": module, "f": method, "t": view, **params}
            return self.base_url + "index.php?" + urllib.parse.urlencode(query)
        # Classic PATH_INFO consumes values in the controller argument order.
        values = [str(value) for value in params.values()]
        path = "-".join([module, method] + values) + "." + view
        return self.base_url + urllib.parse.quote(path, safe=".-_")

    def _request(self, url, *, data=None, content_type=None, length=None,
                 writing=False):
        headers = {"Accept": "application/json,text/html;q=0.8",
                   "User-Agent": "BugDesk/1.0 (local ZenTao assistant)",
                   "Referer": self.base_url, "X-Requested-With": "XMLHttpRequest"}
        if content_type:
            headers["Content-Type"] = content_type
        if length is not None:
            headers["Content-Length"] = str(length)
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST" if data is not None else "GET")
        try:
            with self._opener.open(req, timeout=self.timeout) as response:
                body = response.read(self.RESPONSE_LIMIT + 1)
                if len(body) > self.RESPONSE_LIMIT:
                    raise ConnectorError("禅道返回的数据过大，暂时无法确认结果。", uncertain=writing)
                charset = response.headers.get_content_charset() or "utf-8"
                return body.decode(charset, errors="replace").lstrip("\ufeff")
        except ConnectorError:
            raise
        except urllib.error.HTTPError as exc:
            # No raw response is echoed: authentication errors sometimes contain
            # the posted payload. Auth-denial statuses mean this POST was rejected.
            if exc.code in (401, 403):
                message = "禅道拒绝访问，请检查登录状态、账号权限或公司的单点登录要求。"
                unknown = False
            elif 300 <= exc.code < 400:
                message = "禅道跳转了请求。请使用最终的禅道地址；提交结果需要在禅道核对。"
                unknown = writing
            else:
                message = f"禅道返回 HTTP {exc.code}，请检查地址或联系管理员。"
                unknown = writing
            raise ConnectorError(message, uncertain=unknown) from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError,
                ValueError, LookupError, http.client.HTTPException):
            raise ConnectorError(
                "无法访问禅道。回公司后请连接公司网络或 VPN，并检查禅道地址。"
                if not writing else
                "提交请求未取得可靠响应，Bug 可能已经创建。请先到禅道核对，勿直接重复提交。",
                uncertain=writing) from None

    @staticmethod
    def _json(body, *, writing=False):
        try:
            value = json.loads(body)
        except (ValueError, TypeError):
            raise ConnectorError(
                "禅道未返回可识别的 JSON，可能是登录页、单点登录或公司定制页面。"
                + (" 本次提交结果不明，请到禅道核对。" if writing else ""),
                uncertain=writing) from None
        if not isinstance(value, (dict, list)):
            raise ConnectorError("禅道返回的数据格式无法识别。", uncertain=writing)
        return value

    @staticmethod
    def _view(value):
        if not isinstance(value, dict):
            raise ConnectorError("禅道页面数据格式无法识别。")
        if value.get("status") in ("fail", "failed", "error") or value.get("result") in (False, "fail", "failed"):
            raise ConnectorError("禅道未允许读取页面，请检查登录状态和账号权限。")
        if "data" in value:
            data = value["data"]
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except ValueError:
                    raise ConnectorError("禅道返回的页面内容无法解析。") from None
            if isinstance(data, dict):
                return data
        return value

    def _get(self, module, method, params=None):
        return self._json(self._request(self._url(module, method, params)))

    def _auth_identity(self, value):
        # A bare result=success or HTTP 200 is not evidence of authentication.
        user = value.get("user", {}) if isinstance(value, dict) else {}
        return (value.get("status") == "success" and isinstance(user, dict)
                and user.get("account") == self.account and self.account != "guest")

    def connect(self):
        self.connected = False
        if not self.account or not self._password:
            raise ConnectorError("请填写禅道账号和密码。密码只在本次运行的内存中使用。")
        rand = None
        last_error = None
        # Route discovery is read-only. We never try the login password twice.
        for route in ("get", "path"):
            self._route = route
            try:
                candidate = self._request(self._url("user", "refreshRandom", route=route)).strip()
                if re.fullmatch(r"\d{1,12}", candidate):
                    rand = candidate
                    break
                last_error = ConnectorError("此地址未提供禅道的经典登录接口，可能需要公司单点登录适配。")
            except ConnectorError as exc:
                last_error = exc
        if rand is None:
            raise last_error or ConnectorError("无法读取禅道登录随机数。")
        password_md5 = hashlib.md5(self._password.encode("utf-8")).hexdigest()
        password_hash = hashlib.md5((password_md5 + rand).encode("ascii")).hexdigest()
        fields = {"account": self.account, "password": password_hash,
                  "verifyRand": rand, "keepLogin": "0", "referer": self.base_url}
        body = self._request(self._url("user", "login"),
                             data=urllib.parse.urlencode(fields).encode("utf-8"),
                             content_type="application/x-www-form-urlencoded")
        reply = self._json(body)
        if not self._auth_identity(reply):
            raise ConnectorError("登录未成功。请检查账号密码；若公司使用验证码或单点登录，需要管理员适配。")
        check = self._get("user", "login")
        if not self._auth_identity(check):
            raise ConnectorError("账号验证通过，但禅道登录会话未保留。请检查公司代理、Cookie 或单点登录设置。")
        self.connected = True
        options = {"products": [], "users": []}
        warnings = []
        try:
            data = self._view(self._get("product", "index", {"locate": "no"}))
            options["products"] = _options(data.get("products", {}))
            if options["products"]:
                form = self._read_form(options["products"][0]["value"])
                options["users"] = _options(form.get("users", {}))
        except ConnectorError:
            warnings.append("菜单暂未读取成功，可在公共信息中手动填写 ID。")
        return {"connected": True,
                "message": "登录会话已验证。公司定制字段与附件上传仍需首次单条提交验证。" + "".join(warnings),
                "options": options}

    def _require_connected(self):
        if not self.connected:
            raise ConnectorError("请先连接禅道，再获取菜单或提交。")

    def _read_form(self, product, project="", execution="", *, html_form=False):
        extras = ",".join(f"{key}={value}" for key, value in
                          (("projectID", project), ("executionID", execution)) if value)
        params = {"productID": str(product), "branch": "0", "extras": extras}
        data = self._view(self._get("bug", "create", params))
        if not ("products" in data and ("builds" in data or "moduleOptionMenu" in data)):
            raise ConnectorError("无法识别提 Bug 表单，请检查账号权限或公司定制页面。")
        if html_form:
            body = self._request(self._url("bug", "create", params, view="html"))
            parser = _FormParser()
            parser.feed(body)
            if not any(name in parser.selects for name in ("product", "openedBuild[]")):
                raise ConnectorError("无法读取提 Bug 表单，可能登录会话已过期。")
            data["_html"] = parser
        self._forms[(str(product), str(project), str(execution))] = data
        return data

    def options(self, product, project="", execution=""):
        self._require_connected()
        if not product:
            return {"projects": [], "executions": [], "modules": [], "builds": [], "priorities": [], "probabilities": [], "probability_diagnostic": None}
        data = self._read_form(product, project, execution)
        result = {"products": _options(data.get("products", {})),
                  "projects": _options(data.get("projects", {})),
                  "executions": _options(data.get("executions", {})),
                  "modules": _options(data.get("moduleOptionMenu", {})),
                  "builds": _options(data.get("builds", {})),
                  "users": _options(data.get("users", {})), "priorities": [], "probabilities": [], "probability_diagnostic": None}
        # The standard 18.11 form has no probability field. Only use an actual
        # company's observed field and values, including differently named selects.
        parser = None
        try:
            data = self._read_form(product, project, execution, html_form=True)
            parser = data["_html"]
            result["priorities"] = self._picker_choices(parser, "pri")
            field, choices = self._probability_field(parser)
            result["probabilities"] = choices
            if field:
                result["probability_field"] = field
            if not field or not choices:
                result["warnings"] = ["未读取到可用的公司“概率”选项。请重新加载菜单；无法识别时会在提交前停止。"]
                result["probability_diagnostic"] = _probability_diagnostic(parser)
        except ConnectorError as exc:
            result["warnings"] = [str(exc) if "概率" in str(exc) else
                                  "未读取到公司“概率”选项；请重新加载菜单，无法识别时会在提交前停止。"]
            result["probability_diagnostic"] = _probability_diagnostic(parser)
        return result

    @staticmethod
    def _picker_choices(parser, name):
        return [dict(choice) for choice in parser.selects.get(name, [])
                if choice["value"] and choice["label"]]

    @staticmethod
    def _probability_field(parser):
        candidates = []
        for name, choices in parser.selects.items():
            base = name.removesuffix("[]")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\[\])?", name):
                continue
            # Keep identity and other ordinary controls separate even if a
            # nearby field shares their table row/input-group.
            if base in ("product", "project", "execution", "module", "openedBuild", "assignedTo",
                        "type", "severity", "pri", "os", "branch"):
                continue
            if not any("disabled" not in control.attrs for control in parser.select_nodes.get(name, [])):
                continue
            labels = [re.sub(r"\s+", "", caption) for caption in parser.captions(name)]
            observed_caption = any(re.fullmatch(
                r"(?:发生|出现|复现|重现)?概率(?:[:：*＊]|[（(][^()（）]{0,12}[)）])*", label)
                for label in labels)
            # Some classic company forms reuse the browser slot for probability.
            # Its real local caption proves that meaning; the browser name or
            # the option text alone never does. Preserve browser[] for posting.
            if base == "browser" and not observed_caption:
                continue
            observed_alias = base.lower() in ("probability", "chance", "occurprobability", "occurrenceprobability")
            # frequency is common in company extensions, but its name alone
            # could also describe another business fact. Require the caption.
            if observed_caption or observed_alias:
                selected = []
                for choice in choices:
                    if choice["value"] and choice["label"] and choice not in selected:
                        selected.append(dict(choice))
                candidates.append((name, selected))
        if len(candidates) > 1:
            raise ConnectorError("读取到多个公司“概率”字段，无法确定提交目标，请联系管理员检查表单。")
        return candidates[0] if candidates else ("", [])

    @staticmethod
    def _resolve_probability(value, choices):
        """Accept only an observed value or an unambiguous exact display label."""
        value = str(value).strip()
        matching = {choice["value"] for choice in choices
                    if choice["value"] == value or choice["label"].strip() == value}
        if len(matching) == 1:
            return next(iter(matching))
        if len(matching) > 1:
            raise ConnectorError("公司“概率”选项名称不唯一，请重新加载菜单后选择具体选项。")
        raise ConnectorError("所选“概率”已不在公司菜单中，请重新加载菜单并选择，不能按截图文字推测编号。")

    @staticmethod
    def _description(bug):
        sections = []
        for heading, key in (("前置条件", "preconditions"), ("步骤", "steps"),
                             ("结果", "actual"), ("期望", "expected")):
            value = str(bug.get(key, "")).strip()
            if value:
                text = html.escape(value).replace("\r\n", "\n").replace("\n", "<br>")
                sections.append(f"<p>[{heading}]</p><p>{text}</p>")
        return "".join(sections)

    @staticmethod
    def _positive_id(value):
        try:
            if isinstance(value, bool):
                return None
            number = int(str(value))
            return number if number > 0 else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _upload_name(attachment):
        name = str(attachment.get("name") or Path(attachment["path"]).name)
        if any(char in name for char in ('\r', '\n', '"')):
            raise ConnectorError("附件文件名包含不支持的字符，请先改名后重新扫描。")
        normalized = name.replace("\\", "/")
        parts = normalized.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ConnectorError("附件文件名的相对路径无法识别，请重新扫描。")
        if len(parts) == 1:
            return parts[0]
        suffix = Path(parts[-1]).suffix
        stem = parts[-1][:-len(suffix)] if suffix else parts[-1]
        token = hashlib.sha256(str(attachment.get("id", normalized)).encode()).hexdigest()[:8]
        prefix = " — ".join(parts[:-1] + [stem])
        return f"{prefix} — {token}{suffix}"

    def _prepare_multipart(self, fields, attachments):
        boundary = "BugDesk" + secrets.token_hex(24)
        # Roll to a temporary file for larger videos instead of holding them in RAM.
        stream = tempfile.SpooledTemporaryFile(max_size=2 * 1024 * 1024)
        try:
            def emit(value):
                stream.write(value.encode("utf-8") if isinstance(value, str) else value)
            for key, value in fields:
                emit(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n')
            for attachment in attachments:
                path = Path(attachment["path"])
                name = self._upload_name(attachment)
                try:
                    before = path.stat()
                    if not path.is_file() or before.st_size <= 0:
                        raise ConnectorError(f"附件“{name}”为空或已不存在，请重新扫描。")
                    if before.st_size > self.FILE_LIMIT:
                        raise ConnectorError(f"附件“{name}”超过 500 MB，请压缩或在禅道单独上传。")
                    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
                    emit(f'--{boundary}\r\nContent-Disposition: form-data; name="files[]"; filename="{name}"\r\nContent-Type: {mime}\r\n\r\n')
                    with path.open("rb") as source:
                        while chunk := source.read(1024 * 1024):
                            emit(chunk)
                    emit("\r\n")
                    after = path.stat()
                    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                        raise ConnectorError(f"附件“{name}”在读取期间发生变化，请重新扫描后提交。")
                except OSError:
                    raise ConnectorError(f"无法读取附件“{name}”，请检查文件权限并重新扫描。") from None
            emit(f"--{boundary}--\r\n")
            length = stream.tell()
            stream.seek(0)
            return stream, f"multipart/form-data; boundary={boundary}", length
        except BaseException:
            stream.close()
            raise

    def create_bug(self, bug, settings, attachments):
        self._require_connected()
        if bug.get("remote_id") or bug.get("status") == "uncertain":
            raise ConnectorError("此条 Bug 已有禅道记录或结果待核对，不能重复创建。")
        for key, label in (("title", "标题"), ("steps", "复现步骤"),
                           ("actual", "实际结果"), ("expected", "预期结果")):
            if not str(bug.get(key, "")).strip():
                raise ConnectorError(f"请补齐{label}后再提交。")
        product_id = self._positive_id(settings.get("product", ""))
        if not product_id:
            raise ConnectorError("请选择所属产品，或在公共信息中填写产品 ID。")
        product = str(product_id)
        feedback = str(settings.get("feedbackBy", "")).strip()
        if len(feedback) > 100:
            raise ConnectorError("反馈者最多填写 100 个字符，请修改后再提交。")
        builds = settings.get("openedBuild", [])
        if isinstance(builds, str):
            builds = [value.strip() for value in builds.split(",") if value.strip()]
        if not builds:
            raise ConnectorError("请填写影响版本。若选择主干版本，请使用禅道提供的 trunk 值。")
        project = str(settings.get("project", ""))
        execution = str(settings.get("execution", ""))
        # Reading the form immediately before posting catches expired sessions,
        # product permissions and changed custom fields without risking a write.
        form = self._read_form(product, project, execution, html_form=True)
        parser = form["_html"]
        fields = [(key, value) for key, value in parser.hidden.items()]
        ordinary = {"product": product, "project": project or "0", "execution": execution or "0",
                    "module": str(settings.get("module", "0")), "assignedTo": str(settings.get("assignedTo", "")),
                    "feedbackBy": feedback,
                    "type": str(settings.get("type", "codeerror")), "severity": str(settings.get("severity", "3")),
                    "pri": str(settings.get("pri", "4")), "os": str(settings.get("os", "")),
                    "title": str(bug["title"]).strip(), "steps": self._description(bug), "branch": "0"}
        priorities = self._picker_choices(parser, "pri")
        if priorities and ordinary["pri"] not in {choice["value"] for choice in priorities}:
            raise ConnectorError("所选优先级已不在公司菜单中，请重新加载菜单并重新选择。本条未发送到禅道。")
        fields += list(ordinary.items())
        fields += [("openedBuild[]", str(value)) for value in builds]
        probability = str(settings.get("probability", "")).strip()
        probability_name = ""
        if probability:
            try:
                probability_name, choices = self._probability_field(parser)
            except ConnectorError as exc:
                raise ConnectorError(str(exc) + " 本条未发送到禅道。") from None
            if not probability_name:
                raise ConnectorError("未读取到公司“概率”字段，请重新加载菜单；仍无选项时需核对公司表单。本条未发送到禅道。")
            if not choices:
                raise ConnectorError("公司“概率”字段没有可用选项，请重新加载菜单。本条未发送到禅道。")
            try:
                probability = self._resolve_probability(probability, choices)
            except ConnectorError as exc:
                raise ConnectorError(str(exc) + " 本条未发送到禅道。") from None
            fields.append((probability_name, probability))
        else:
            # Even an unfilled extension can produce a required-field response.
            # Recognize that actual form key as validation, rather than marking
            # a clear validation rejection as an uncertain creation.
            try:
                probability_name, _ = self._probability_field(parser)
            except ConnectorError:
                pass
        stream, content_type, length = self._prepare_multipart(fields, attachments)
        try:
            raw = self._request(self._url("bug", "create", {"productID": product, "branch": "0", "extras": ""}),
                                data=stream, content_type=content_type, length=length, writing=True)
        finally:
            stream.close()
        reply = self._json(raw, writing=True)
        if not isinstance(reply, dict):
            raise ConnectorError("提交响应无法识别，请先到禅道核对。", uncertain=True)
        remote_id = self._positive_id(reply.get("id"))
        remote_url = self._url("bug", "view", {"bugID": remote_id}, view="html") if remote_id else ""
        if reply.get("result") != "success":
            message = reply.get("message")
            # A validation dictionary for known form fields is emitted before the
            # insert. Other failures may come after insertion (e.g. upload SQL).
            known_fields = set(ordinary) | {"openedBuild", "deadline", "probability"}
            if probability_name:
                known_fields.update((probability_name, probability_name.removesuffix("[]")))
            validation = isinstance(message, dict) and bool(message) and set(message) <= known_fields
            names = {"title": "标题", "openedBuild": "影响版本", "product": "所属产品",
                     "steps": "复现描述", "execution": "所属执行", "deadline": "截止日期",
                     "feedbackBy": "反馈者"}
            if probability_name:
                names[probability_name] = names[probability_name.removesuffix("[]")] = "发生概率"
            details = "、".join(names.get(key, "公共字段") for key in message) if validation else ""
            raise ConnectorError("禅道校验未通过，请检查" + details + "。" if validation else
                                 "禅道未确认保存成功，可能已有记录。请到禅道核对后处理。",
                                 uncertain=not validation, remote_id=remote_id, remote_url=remote_url,
                                 partial=bool(remote_id))
        if not remote_id:
            raise ConnectorError("禅道返回保存成功，但没有 Bug 编号，请先到禅道核对。", uncertain=True)
        if reply.get("locate"):
            raise ConnectorError("禅道检测到可能重复的 Bug，并返回已有记录。请核对标题与附件，未再次创建。",
                                 partial=True, remote_id=remote_id, remote_url=remote_url)
        try:
            detail = self._view(self._get("bug", "view", {"bugID": remote_id})).get("bug", {})
        except ConnectorError:
            raise ConnectorError("已取得 Bug 编号，但无法读取详情确认附件，请在禅道核对。",
                                 partial=True, remote_id=remote_id, remote_url=remote_url) from None
        if (not isinstance(detail, dict) or self._positive_id(detail.get("id")) != remote_id
                or html.unescape(str(detail.get("title", ""))) != ordinary["title"]
                or str(detail.get("product", "")) != product):
            raise ConnectorError("已取得 Bug 编号，但详情与本次内容无法核对，请在禅道检查。",
                                 partial=True, remote_id=remote_id, remote_url=remote_url)
        # A saved ID is insufficient if a company extension silently discarded
        # fields. Compare facts and selected values, tolerating HTML formatting.
        def values(value):
            if isinstance(value, (list, tuple)):
                return {str(item).strip() for item in value if str(item).strip()}
            return {part.strip() for part in str(value or "").split(",") if part.strip()}
        mismatch = []
        if ordinary["feedbackBy"] and html.unescape(str(detail.get("feedbackBy", ""))) != ordinary["feedbackBy"]:
            mismatch.append("feedbackBy")
        for key in ("project", "execution", "module", "assignedTo", "type", "severity", "pri", "os"):
            expected = ordinary[key]
            specified = key in ("type", "severity", "pri") or bool(str(settings.get(key, "")))
            if specified and values(detail.get(key)) != values(expected):
                mismatch.append(key)
        if values(detail.get("openedBuild")) != values(builds):
            mismatch.append("openedBuild")
        if probability and values(detail.get(probability_name.removesuffix("[]"))) != values(probability):
            mismatch.append("probability")
        remote_description = _fact_text(detail.get("steps", ""))
        for key in ("preconditions", "steps", "actual", "expected"):
            fact = re.sub(r"\s+", "", str(bug.get(key, "")))
            if fact and fact not in remote_description:
                mismatch.append("description")
                break
        files = detail.get("files", {})
        files = list(files.values()) if isinstance(files, dict) else files
        if not isinstance(files, list):
            files = []
        remaining = [file for file in files if isinstance(file, dict)
                     and self._positive_id(file.get("size"))]
        upload_status = {}
        for attachment in attachments:
            name = self._upload_name(attachment)
            match = next((file for file in remaining if html.unescape(str(file.get("title", ""))) == name), None)
            if match:
                remaining.remove(match)
            upload_status[str(attachment["id"])] = "uploaded" if match else "unconfirmed"
        if mismatch:
            raise ConnectorError("Bug 已创建，但部分公共信息或复现描述未从详情确认。请打开禅道核对修改，勿重复创建。",
                                 partial=True, remote_id=remote_id, remote_url=remote_url,
                                 upload_status=upload_status)
        if any(value != "uploaded" for value in upload_status.values()):
            raise ConnectorError("Bug 已创建，但部分附件未在详情中确认。请打开禅道补齐附件，勿重复创建。",
                                 partial=True, remote_id=remote_id, remote_url=remote_url,
                                 upload_status=upload_status)
        return {"id": remote_id, "url": remote_url, "upload_status": upload_status,
                "files": files, "message": "Bug 与所选附件已从禅道详情确认。" if attachments else
                "Bug 已确认创建，本次没有上传附件。"}
