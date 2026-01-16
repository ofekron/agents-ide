# Agents IDE Installation Wizard for Windows
# Run as: powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host $Text -ForegroundColor Cyan -BackgroundColor DarkBlue
    Write-Host ""
}

function Write-Step {
    param([string]$Text)
    Write-Host ""
    Write-Host ">>> $Text" -ForegroundColor White -BackgroundColor DarkGray
}

function Write-Success {
    param([string]$Text)
    Write-Host "[OK] $Text" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Text)
    Write-Host "[!] $Text" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Text)
    Write-Host "[X] $Text" -ForegroundColor Red
}

function Ask-User {
    param(
        [string]$Prompt,
        [string]$Default
    )
    $response = Read-Host "$Prompt [$Default]"
    if ([string]::IsNullOrWhiteSpace($response)) {
        return $Default
    }
    return $response
}

function Confirm {
    param([string]$Prompt)
    $response = Read-Host "$Prompt (y/n)"
    return $response -match '^[Yy]'
}

# Header
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   Agents IDE Installation Wizard" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Check Python
Write-Step "Step 1: Checking Python..."
try {
    $pythonVersion = (python --version 2>&1) -replace "Python ", ""
    $parts = $pythonVersion.Split(".")
    $major = [int]$parts[0]
    $minor = [int]$parts[1]

    if ($major -ge 3 -and $minor -ge 11) {
        Write-Success "Python $pythonVersion found"
    } else {
        Write-Error "Python 3.11+ required (found $pythonVersion)"
        Write-Host ""
        Write-Host "Please install Python 3.11+ from: https://www.python.org/downloads/" -ForegroundColor Yellow
        Read-Host "Press Enter to exit"
        exit 1
    }
} catch {
    Write-Error "Python not found"
    Write-Host ""
    Write-Host "Please install Python 3.11+ from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "Make sure to check 'Add Python to PATH' during installation." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Step 2: Check Node.js
Write-Step "Step 2: Checking Node.js..."
try {
    $nodeVersion = (node --version 2>&1)
    Write-Success "Node.js $nodeVersion found"
} catch {
    Write-Warning "Node.js not found"
    Write-Host ""
    if (Confirm "Would you like instructions to install Node.js?") {
        Write-Host ""
        Write-Host "Download and install Node.js from: https://nodejs.org/" -ForegroundColor Yellow
        Write-Host "Choose the LTS version for stability." -ForegroundColor Yellow
        Write-Host ""
        Read-Host "Press Enter after installing Node.js to continue"

        try {
            $nodeVersion = (node --version 2>&1)
            Write-Success "Node.js $nodeVersion found"
        } catch {
            Write-Error "Node.js still not found. Please install and try again."
            Read-Host "Press Enter to exit"
            exit 1
        }
    } else {
        Write-Error "Node.js is required. Exiting."
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# Step 3: Install pyright
Write-Step "Step 3: Installing pyright LSP server..."
$pyrightInstalled = Get-Command pyright-langserver -ErrorAction SilentlyContinue
if ($pyrightInstalled) {
    Write-Success "pyright-langserver already installed"
    if (Confirm "Reinstall/update pyright?") {
        Write-Host "Running: npm install -g pyright" -ForegroundColor Gray
        npm install -g pyright
    }
} else {
    if (Confirm "Install pyright globally via npm?") {
        Write-Host "Running: npm install -g pyright" -ForegroundColor Gray
        npm install -g pyright
        if ($LASTEXITCODE -eq 0) {
            Write-Success "pyright installed"
        } else {
            Write-Error "Failed to install pyright"
        }
    } else {
        Write-Warning "Skipping pyright installation"
        Write-Host "  You'll need to install it manually: npm install -g pyright" -ForegroundColor Yellow
    }
}

# Step 4: Install agents-ide
Write-Step "Step 4: Installing agents-ide..."
Write-Host ""
Write-Host "Installation options:" -ForegroundColor White
Write-Host "  1) Development mode (editable install, recommended for contributors)"
Write-Host "  2) Regular install"
Write-Host ""
$installMode = Ask-User "Choose installation mode" "1"

if ($installMode -eq "1") {
    Write-Host "Running: pip install -e ." -ForegroundColor Gray
    pip install -e .
} else {
    Write-Host "Running: pip install ." -ForegroundColor Gray
    pip install .
}

if ($LASTEXITCODE -eq 0) {
    Write-Success "agents-ide installed"
} else {
    Write-Error "Failed to install agents-ide"
    Read-Host "Press Enter to exit"
    exit 1
}

# Step 5: Configure Claude Code
Write-Step "Step 5: Configure Claude Code"
Write-Host ""

$claudeSettings = "$env:USERPROFILE\.claude\settings.json"
if (Test-Path $claudeSettings) {
    Write-Host "Found existing Claude Code settings at: $claudeSettings"
    if (Confirm "Would you like to see the MCP configuration to add?") {
        Write-Host ""
        Write-Host "Add this to your mcpServers in settings.json:" -ForegroundColor Cyan
        Write-Host ""
        Write-Host '  "agents-ide": {'
        Write-Host '    "command": "agents-ide"'
        Write-Host '  }'
        Write-Host ""
    }
} else {
    Write-Host "Claude Code settings not found."
    if (Confirm "Create settings file with agents-ide configured?") {
        $claudeDir = "$env:USERPROFILE\.claude"
        if (!(Test-Path $claudeDir)) {
            New-Item -ItemType Directory -Path $claudeDir | Out-Null
        }
        $settingsContent = @'
{
  "mcpServers": {
    "agents-ide": {
      "command": "agents-ide"
    }
  }
}
'@
        Set-Content -Path $claudeSettings -Value $settingsContent
        Write-Success "Created $claudeSettings"
    }
}

# Step 6: Install Skill Documentation
Write-Step "Step 6: Install Skill Documentation"
Write-Host ""
Write-Host "The agents-ide skill provides usage guides for Claude Code."
Write-Host ""

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillSource = Join-Path $scriptDir "skill"

if (Test-Path $skillSource) {
    Write-Host "Install location options:" -ForegroundColor White
    Write-Host "  1) Global (~\.claude\skills\agents-ide-usage\)"
    Write-Host "  2) Current project (.claude\skills\agents-ide-usage\)"
    Write-Host "  3) Skip"
    Write-Host ""
    $skillLocation = Ask-User "Choose install location" "1"

    switch ($skillLocation) {
        "1" {
            $skillDest = "$env:USERPROFILE\.claude\skills\agents-ide-usage"
            if (!(Test-Path $skillDest)) {
                New-Item -ItemType Directory -Path $skillDest -Force | Out-Null
            }
            Copy-Item -Path "$skillSource\*" -Destination $skillDest -Recurse -Force
            Write-Success "Skill installed to $skillDest"
        }
        "2" {
            $skillDest = ".claude\skills\agents-ide-usage"
            if (!(Test-Path $skillDest)) {
                New-Item -ItemType Directory -Path $skillDest -Force | Out-Null
            }
            Copy-Item -Path "$skillSource\*" -Destination $skillDest -Recurse -Force
            Write-Success "Skill installed to $skillDest"
        }
        default {
            Write-Host "Skipping skill installation."
        }
    }
} else {
    Write-Warning "Skill folder not found in package"
}

# Done
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "      Installation Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Commands available:"
Write-Host "  agents-ide        - Run MCP server"
Write-Host "  agents-ide-daemon - Manage LSP daemon"
Write-Host ""
Write-Host "Test the daemon:"
Write-Host "  agents-ide-daemon start"
Write-Host "  agents-ide-daemon status"
Write-Host ""
Read-Host "Press Enter to exit"
