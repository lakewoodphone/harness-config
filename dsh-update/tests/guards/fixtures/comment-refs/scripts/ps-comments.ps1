<#
  FIXTURE for tests/guards/comment-refs.mjs — PowerShell `#`, `<# … #>` and here-strings.
#>

# @deepseek-ai/dsh-fixture-ps-comment must NOT be reported
<# @deepseek-ai/dsh-fixture-ps-block must NOT be reported #>

$Bin = '@deepseek-ai/dsh-fixture-ps-string'
$Own = 'dsh-plugin-fixture-ps-own'
$Quoted = "a literal # @deepseek-ai/dsh-fixture-ps-hash-in-string stays content"

Write-Host $Bin $Own $Quoted # @deepseek-ai/dsh-fixture-ps-trailing must NOT be reported
