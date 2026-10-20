[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('context', 'stage')]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$ConnectionFile,
    [string]$InputFile
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$script:MaximumBytes = 1024 * 1024
$script:MaximumResponseBytes = 8 * 1024 * 1024
$script:StrictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)

function Stop-Safely([string]$Message) {
    $failure = New-Object System.InvalidOperationException($Message)
    $failure.Data['BugDeskSafe'] = $true
    throw $failure
}

function Convert-JsonText([string]$Content) {
    $arguments = @{ InputObject = $Content; ErrorAction = 'Stop' }
    # Recent PowerShell 7 otherwise turns ISO date strings into DateTime values;
    # connection expiry and testcase facts must retain their JSON string types.
    if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey('DateKind')) {
        $arguments['DateKind'] = 'String'
    }
    return ConvertFrom-Json @arguments
}

function Read-JsonFile([string]$FilePath) {
    $stream = $null
    $memory = $null
    try {
        $absolutePath = [System.IO.Path]::GetFullPath($FilePath)
        if ($absolutePath -notmatch '^[A-Za-z]:[\\/]' -or $absolutePath.StartsWith('\\')) {
            Stop-Safely '只接受本机磁盘上的连接或建议文件。'
        }
        $stream = [System.IO.File]::Open($absolutePath, [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
        if ($stream.Length -gt $script:MaximumBytes) {
            Stop-Safely 'JSON 文件超过 1 MiB，请减少本次用例数量。'
        }
        $memory = New-Object System.IO.MemoryStream
        $buffer = New-Object byte[] 8192
        while (($count = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            if ($memory.Length + $count -gt $script:MaximumBytes) {
                Stop-Safely 'JSON 文件超过 1 MiB，请减少本次用例数量。'
            }
            $memory.Write($buffer, 0, $count)
        }
        $content = $script:StrictUtf8.GetString($memory.ToArray()).TrimStart([char]0xFEFF)
        $value = Convert-JsonText $content
        if ($value -isnot [System.Management.Automation.PSCustomObject]) {
            Stop-Safely 'JSON 文件需要包含一个对象。'
        }
        return $value
    }
    catch {
        if ($_.Exception.Data.Contains('BugDeskSafe')) { throw }
        Stop-Safely '无法读取有效的本地 UTF-8 JSON 文件，请重新检查文件。'
    }
    finally {
        if ($memory) { $memory.Dispose() }
        if ($stream) { $stream.Dispose() }
    }
}

function Assert-ObjectKeys($Value, [string[]]$Required, [string[]]$Optional = @()) {
    if ($Value -isnot [System.Management.Automation.PSCustomObject]) {
        Stop-Safely '连接或建议对象格式不正确。'
    }
    $names = @($Value.PSObject.Properties.Name)
    foreach ($key in $Required) {
        if ($names -cnotcontains $key) { Stop-Safely '连接或建议缺少必需字段。' }
    }
    foreach ($key in $names) {
        if ($Required -cnotcontains $key -and $Optional -cnotcontains $key) {
            Stop-Safely '连接或建议包含不支持的字段。'
        }
    }
}

function Assert-Text($Value, [int]$Limit) {
    if ($Value -isnot [string] -or $Value.Length -gt $Limit -or $Value.Contains([char]0)) {
        Stop-Safely '建议文字字段过长或格式不正确。'
    }
}

function Test-JsonInteger($Value) {
    # Windows PowerShell 5.1 and PowerShell 7 use different integer widths when
    # decoding JSON. Both are valid; floating point and string numbers are not.
    return ($Value -is [int] -or $Value -is [long])
}

function Invoke-LocalJson([string]$Route, [string]$Method, [string]$Token, [byte[]]$Body) {
    $response = $null
    $responseStream = $null
    $memory = $null
    try {
        $request = [System.Net.HttpWebRequest]::Create($script:LocalBase + $Route)
        $request.Method = $Method
        $request.Proxy = $null
        $request.AllowAutoRedirect = $false
        $request.Timeout = 15000
        $request.ReadWriteTimeout = 15000
        $request.Accept = 'application/json'
        if ($Token) { $request.Headers['X-BugDesk-WorkBuddy-Token'] = $Token }
        if ($Method -eq 'POST') {
            $request.ContentType = 'application/json; charset=utf-8'
            $request.ContentLength = $Body.Length
            $outgoing = $request.GetRequestStream()
            try { $outgoing.Write($Body, 0, $Body.Length) }
            finally { $outgoing.Dispose() }
        }
        $response = $request.GetResponse()
        $statusCode = [int]$response.StatusCode
        if ($statusCode -lt 200 -or $statusCode -ge 300) {
            Stop-Safely ('BugDesk 返回 HTTP ' + $statusCode + '，请回 BugDesk 重新连接并读取上下文。')
        }
        $responseStream = $response.GetResponseStream()
        $memory = New-Object System.IO.MemoryStream
        $buffer = New-Object byte[] 8192
        while (($count = $responseStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            if ($memory.Length + $count -gt $script:MaximumResponseBytes) {
                Stop-Safely '本地接口响应超过 8 MiB，请减少当前批次内容。'
            }
            $memory.Write($buffer, 0, $count)
        }
        $json = $script:StrictUtf8.GetString($memory.ToArray())
        if ($json.Contains($script:SessionToken)) {
            Stop-Safely '本地接口返回了不应公开的连接信息，请重新连接。'
        }
        $value = Convert-JsonText $json
        if ($value -isnot [System.Management.Automation.PSCustomObject]) {
            Stop-Safely '本地接口响应格式不正确，请重新连接。'
        }
        return $value
    }
    catch [System.Net.WebException] {
        $failedResponse = $_.Exception.Response
        if ($failedResponse) {
            $statusCode = [int]$failedResponse.StatusCode
            $failedResponse.Dispose()
            Stop-Safely ('BugDesk 返回 HTTP ' + $statusCode + '，请回 BugDesk 重新连接并读取上下文。')
        }
        Stop-Safely '无法连接本机 BugDesk，请确认工具已打开并重新复制连接提示。'
    }
    catch {
        if ($_.Exception.Data.Contains('BugDeskSafe')) { throw }
        Stop-Safely '本地接口响应无法读取，请重新连接并读取上下文。'
    }
    finally {
        if ($memory) { $memory.Dispose() }
        if ($responseStream) { $responseStream.Dispose() }
        if ($response) { $response.Dispose() }
    }
}

try {
    $session = Read-JsonFile $ConnectionFile
    Assert-ObjectKeys $session @('schema', 'url', 'instance', 'token', 'expires_at')
    if (-not (Test-JsonInteger $session.schema) -or $session.schema -ne 1) {
        Stop-Safely '连接文件版本不支持，请在 BugDesk 重新开启 WorkBuddy 连接。'
    }
    Assert-Text $session.url 200
    Assert-Text $session.instance 200
    Assert-Text $session.token 200
    Assert-Text $session.expires_at 100
    $localUri = $null
    if ($session.url -cnotmatch '^http://127\.0\.0\.1:[1-9][0-9]{0,4}/$' -or
        -not [System.Uri]::TryCreate($session.url, [System.UriKind]::Absolute, [ref]$localUri) -or
        $localUri.Host -cne '127.0.0.1' -or $localUri.Scheme -cne 'http' -or $localUri.Port -lt 1 -or
        $localUri.Port -gt 65535 -or $localUri.AbsolutePath -cne '/' -or $localUri.UserInfo -or
        $localUri.Query -or $localUri.Fragment) {
        Stop-Safely '连接地址必须是本机 127.0.0.1 的 BugDesk 地址。'
    }
    if ($session.instance -cnotmatch '^[A-Za-z0-9_-]{8,200}$' -or
        $session.token -cnotmatch '^[A-Za-z0-9_-]{20,200}$') {
        Stop-Safely '连接标识格式不正确，请重新复制 BugDesk 连接提示。'
    }
    $expiry = [System.DateTimeOffset]::MinValue
    if ($session.expires_at -cnotmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,7})?(?:Z|[+-]\d{2}:\d{2})$' -or
        -not [System.DateTimeOffset]::TryParse($session.expires_at,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::None, [ref]$expiry) -or
        $expiry -le [System.DateTimeOffset]::UtcNow) {
        Stop-Safely 'WorkBuddy 连接已过期或无效，请在 BugDesk 重新开启连接。'
    }
    $script:LocalBase = $session.url.TrimEnd('/')
    $script:SessionToken = $session.token
    $health = Invoke-LocalJson '/health' 'GET' '' $null
    if (@($health.PSObject.Properties.Name) -cnotcontains 'app' -or
        @($health.PSObject.Properties.Name) -cnotcontains 'instance' -or
        $health.app -cne 'BugDesk' -or $health.instance -cne $session.instance) {
        Stop-Safely '本机程序与连接文件不一致，请重新打开 BugDesk 连接。'
    }

    if ($Action -eq 'context') {
        $context = Invoke-LocalJson '/api/workbuddy/context' 'GET' $session.token $null
        if (@($context.PSObject.Properties.Name) -cnotcontains 'context_id') {
            Stop-Safely 'BugDesk 上下文缺少标识，请更新工具并重新连接。'
        }
        Assert-Text $context.context_id 200
        if (-not $context.context_id.Trim()) { Stop-Safely 'BugDesk 上下文标识为空，请重新读取。' }
        $contextJson = ConvertTo-Json -InputObject $context -Depth 30 -Compress
        if ($contextJson.Contains($script:SessionToken)) { Stop-Safely '本地接口返回了不应公开的连接信息，请重新连接。' }
        [Console]::Out.WriteLine($contextJson)
    }
    else {
        if (-not $InputFile) { Stop-Safely '暂存建议需要指定 UTF-8 JSON 输入文件。' }
        $inputObject = Read-JsonFile $InputFile
        Assert-ObjectKeys $inputObject @('context_id', 'rows')
        Assert-Text $inputObject.context_id 200
        if (-not $inputObject.context_id.Trim()) { Stop-Safely '建议缺少本次上下文标识。' }
        if ($inputObject.rows -isnot [array] -or $inputObject.rows.Count -lt 1 -or $inputObject.rows.Count -gt 300) {
            Stop-Safely '一次需要提供 1 到 300 条用例建议。'
        }
        $limits = @{ case_id = 200; title = 1000; group = 2000; tester = 200; date = 100;
                     preconditions = 20000; steps = 20000; expected = 20000; actual = 20000;
                     suggested_bug_id = 200; match_reason = 1000 }
        $sourceLimits = @{ case_id = 200; title = 1000; group = 2000; tester = 200; date = 100;
                           preconditions = 20000; steps = 20000; expected = 20000; actual = 20000 }
        $sourceCaseCount = 0
        foreach ($row in $inputObject.rows) {
            Assert-ObjectKeys $row @($limits.Keys) @('candidate_bug_ids', 'source_actual', 'review_notes', 'source_cases')
            foreach ($field in $limits.Keys) { Assert-Text $row.$field $limits[$field] }
            if (@($row.PSObject.Properties.Name) -ccontains 'source_cases') {
                if ($row.source_cases -isnot [array] -or $row.source_cases.Count -lt 1 -or $row.source_cases.Count -gt 300) {
                    Stop-Safely '来源用例需要是包含 1 到 300 条的列表。'
                }
                foreach ($sourceCase in $row.source_cases) {
                    Assert-ObjectKeys $sourceCase @($sourceLimits.Keys) @('source_actual')
                    foreach ($field in $sourceLimits.Keys) { Assert-Text $sourceCase.$field $sourceLimits[$field] }
                    if (@($sourceCase.PSObject.Properties.Name) -ccontains 'source_actual') {
                        Assert-Text $sourceCase.source_actual 20000
                    }
                }
                $sourceCaseCount += $row.source_cases.Count
            }
            else {
                # Legacy 1.0.0 rows contain one original case directly.
                $sourceCaseCount += 1
            }
            if ($sourceCaseCount -gt 300) {
                Stop-Safely '一次最多整理 300 条来源用例，请分批整理。'
            }
            if (@($row.PSObject.Properties.Name) -ccontains 'source_actual') {
                Assert-Text $row.source_actual 20000
            }
            if (@($row.PSObject.Properties.Name) -ccontains 'review_notes') {
                if ($row.review_notes -isnot [array] -or $row.review_notes.Count -gt 20) {
                    Stop-Safely '待确认事项需要是列表，且最多 20 条。'
                }
                foreach ($note in $row.review_notes) { Assert-Text $note 2000 }
            }
            if (@($row.PSObject.Properties.Name) -ccontains 'candidate_bug_ids') {
                if ($row.candidate_bug_ids -isnot [array] -or $row.candidate_bug_ids.Count -gt 20) {
                    Stop-Safely '候选 Bug 列表格式不正确。'
                }
                foreach ($candidate in $row.candidate_bug_ids) { Assert-Text $candidate 200 }
            }
        }
        $requestBytes = $script:StrictUtf8.GetBytes((ConvertTo-Json -InputObject $inputObject -Depth 10 -Compress))
        if ($requestBytes.Length -gt $script:MaximumBytes) { Stop-Safely 'JSON 建议超过 1 MiB，请分批整理。' }
        $stage = Invoke-LocalJson '/api/workbuddy/stage' 'POST' $session.token $requestBytes
        if (@($stage.PSObject.Properties.Name) -cnotcontains 'plan_id' -or
            @($stage.PSObject.Properties.Name) -cnotcontains 'summary') {
            Stop-Safely 'BugDesk 暂存响应缺少摘要，请回工具查看结果。'
        }
        Assert-Text $stage.plan_id 200
        if (-not $stage.plan_id.Trim()) { Stop-Safely 'BugDesk 暂存响应缺少标识，请回工具查看结果。' }
        $summary = [ordered]@{}
        foreach ($key in @('total', 'exact', 'suggested', 'unmatched')) {
            if (@($stage.summary.PSObject.Properties.Name) -cnotcontains $key -or
                -not (Test-JsonInteger $stage.summary.$key) -or $stage.summary.$key -lt 0 -or $stage.summary.$key -gt 300) {
                Stop-Safely 'BugDesk 暂存计数格式不正确，请回工具查看结果。'
            }
            $summary[$key] = $stage.summary.$key
        }
        $result = [ordered]@{ ok = $true; plan_id = $stage.plan_id; summary = $summary;
                             message = '已暂存，请回 BugDesk 核对并填入。' }
        [Console]::Out.WriteLine((ConvertTo-Json -InputObject $result -Depth 5 -Compress))
    }
    exit 0
}
catch {
    $safeMessage = '操作未完成，请回 BugDesk 重新连接，并检查本地 JSON 文件。'
    if ($_.Exception.Data.Contains('BugDeskSafe')) { $safeMessage = $_.Exception.Message }
    [Console]::Out.WriteLine((ConvertTo-Json -InputObject @{ ok = $false; error = $safeMessage } -Compress))
    exit 1
}
