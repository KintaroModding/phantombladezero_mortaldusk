-- Mortal Dusk for Phantom Blade Zero.
--
-- On the 66 Days difficulty (EDifficultMode::NightMare) a single death ends the run. The game counts the days left
-- in the player's Blueprint variable RemainingDays (66 at the start): a death takes one (RenewalPlayer.js
-- PushWidgetAndChangeData), and at 0 the death screen starts the game's own end of the run (the bad ending; the save
-- slot later restarts the run from its start). The mod holds RemainingDays at 1 while the player is alive, so the
-- next death reaches 0. Story events also take a day (GameplayEvent.Dead.ChangeDaysLeft, every difficulty); while the
-- player is alive the mod sets the counter back to 1, so only a death ends the run. While the player's health is 0,
-- and DEATH_HOLD_SECONDS after it, the mod never touches the counter, so it never cancels the end. After each change
-- it calls the player's RefreshMaterialParam(), as the game does after its own changes. On the other difficulties
-- the mod changes nothing (the game has no end at 0 days there). The game saves the counter: a run that had the mod
-- keeps 1 day after the mod is removed.
--
-- 66 Days from the first game (like the mod 66 Days Unlocked, without a save change): the difficulty menu's Blueprint
-- function CanSelectNightmare asks the C++ UPBZGameSystem:CanSelectNightMare, which reads the flag
-- bCanSelectNightMare (saved for the account). A hook on that C++ function runs before it (UE4SS hooks on native
-- functions run first): it sets the flag in memory, and right after the check the flag gets its old value back, so
-- the game never saves it.
--
-- Texts, changed at runtime (no Game.locres copy, so no conflict with a text mod such as Let's Die Again): the main
-- menu's "Continue" button, the difficulty menu's 66 Days entry and its two descriptions, and the difficulty
-- refusal dialogs. Only the exact English originals change (TEXTS), so other languages keep the game's texts. Other
-- places that name 66 Days (the save lists, the settings' value switch) stay as they are: the user's choice ("let us
-- stay simple"), after 1.2 tried them. Buttons of the game's class UPBZButtonBase through SetButtonText; text
-- blocks of UPBZCommonLocText (which ignores SetText) through SetPBZFormatText. The menus set these texts through
-- the C++ functions PBZButtonBase:SetButtonText and PBZCommonLocText:SetTextByLocKey; hooks on them run before the
-- function, so the change waits until after it (UE4SS's post callback, else queued with ExecuteInGameThread), and a
-- guard stops the mod's own calls from firing the hooks again. Dialogs (AsyncAction_ShowConfirmation) get their
-- texts in C++ from a key: a hook on BlueprintAsyncActionBase:Activate changes the texts of the action's Descriptor
-- before the dialog is built, and checks the open dialog after it. For TEXT_CHECK_SECONDS after a menu setter fired,
-- a check every TEXT_CHECK_MS looks at the two menus as a backup (FindAllOf runs only then, not during play). Game
-- tests: 1.0 and 1.1 changed every one of these texts in the same call as the game (the post callback), and the
-- dialog through its Descriptor.
--
-- LogDusk (for tests) logs the difficulty and the days of each player, each change of the counter, each death, each
-- answer of the 66 Days check and each text change.
--
-- Settings: the player edits Scripts\config.lua; DEFAULTS holds every setting with its default. A player (or a mod
-- manager) keeps their config.lua across updates, so a new main.lua can meet an older file: a setting that the file
-- lacks, or has with another type, keeps its default, and the log says so. Read a setting only from Settings, never
-- as `config.X or default`: for a true/false setting, `false or true` is true.

local UEHelpers = require("UEHelpers")

local MOD_NAME = "Mortal Dusk"
local VERSION = "1.4"
-- The check of the day counter.
local CHECK_INTERVAL_MS = 250
-- After the player's health was 0, the counter stays untouched this long.
local DEATH_HOLD_SECONDS = 20
-- The days left while the player is alive.
local DAYS_ALIVE = 1
local NIGHTMARE = 4
-- The backup check of the menu texts.
local TEXT_CHECK_MS = 500
local TEXT_CHECK_SECONDS = 3
-- Log at most this many error lines in total.
local MAX_ERROR_LOGS = 5
-- Log at most this many LogDusk lines per game start.
local MAX_DUSK_LOGS = 400

local LIBRARY_PATH = "/Script/ProjectPBZ.Default__PBZBlueprintFunctionLibrary"
local CAN_SELECT_PATH = "/Script/ProjectPBZ.PBZGameSystem:CanSelectNightMare"
local SET_BUTTON_PATH = "/Script/ProjectPBZ.PBZButtonBase:SetButtonText"
local SET_KEY_PATH = "/Script/ProjectPBZ.PBZCommonLocText:SetTextByLocKey"
local ACTIVATE_PATH = "/Script/Engine.BlueprintAsyncActionBase:Activate"
local CONFIRMATION_CLASS = "AsyncAction_ShowConfirmation"
local DIALOG_CLASS = "PBZConfirmationScreen"

-- Buttons only (SetButtonText), by the button's name in its menu: the main menu's "Continue" (other CONTINUE
-- buttons of the game stay).
local BUTTONS = {
    ["CONTINUE"] = { to = "ONE DEATH IS ALL IT TAKES", name = "ContinueGame" },
}
-- Every text (buttons, text blocks, dialogs): exact English originals of Game.locres -> new texts.
local TEXTS = {
    -- UI_SelectDifficutly_09: the difficulty menu's 66 Days entry.
    ["66 DAYS"] = "MORTAL DUSK",
    -- _15 and _16: the difficulty menu's descriptions.
    ["66 days only. Every step could be your last."] = "One life. Your first death is your last.",
    ["Same difficulty as \"Hellwalker,\" but deaths are limited to 66 times. Unlocked after completing the game on any other difficulty."] =
        "Same difficulty as \"Hellwalker,\" but a single death ends the run.",
    -- _11 and _13: the difficulty refusal dialogs (at the start of a run and in the settings).
    ["Difficulty cannot be changed after starting a game on 66 Days."] =
        "Difficulty cannot be changed after starting a game on Mortal Dusk.",
    ["Cannot switch to 66 Days after starting a game."] = "Cannot switch to Mortal Dusk after starting a game.",
}
-- The menus of the backup check: widget class, its buttons and text blocks.
local MENUS = {
    { widget = "WB_StartMenu_V2_C", buttons = { "ContinueGame" }, texts = {} },
    { widget = "WB_DifficultySelect_V2_C", buttons = { "Nightmare" }, texts = { "Desc1", "Desc2" } },
}

-- Every setting with its default; config.lua ships the same names and values (tests\test_main.py checks it).
local DEFAULTS = {
    LogDusk = false,
}

-- Number settings outside these limits use their default.
local LIMITS = {}

local errors = 0
local duskLogs = 0

local function Log(message)
    print(string.format("[%s] %s\n", MOD_NAME, message))
end

local function LogError(message)
    errors = errors + 1
    if errors <= MAX_ERROR_LOGS then
        Log(message)
    end
end

-- DEFAULTS, with the values of Scripts\config.lua over them.
local function ReadSettings()
    local settings = {}
    for name, value in pairs(DEFAULTS) do
        settings[name] = value
    end
    local ok, config = pcall(require, "config")
    if not ok then
        local message = tostring(config)
        if message:find("module 'config' not found", 1, true) then
            Log("No config.lua; every setting uses its default.")
        else
            -- A broken file: Lua's line number and reason, without the long file path.
            local line, reason = message:match("config%.lua:(%d+): ([^\n]*)")
            local detail = line and ("line " .. line .. ": " .. reason) or message:gsub("%s*\n%s*", " ")
            Log("config.lua not read (" .. detail .. "); every setting uses its default.")
        end
        return settings
    end
    if type(config) ~= "table" then
        Log("config.lua does not return a table; every setting uses its default.")
        return settings
    end
    for name, value in pairs(config) do
        local default = DEFAULTS[name]
        if default == nil then
            Log("config.lua: unknown setting " .. tostring(name) .. " ignored.")
        elseif type(value) ~= type(default) then
            Log(string.format("config.lua: %s must be a %s; the default %s is used.", name, type(default),
                tostring(default)))
        else
            local limit = LIMITS[name]
            if limit and (value < limit[1] or value > limit[2]) then
                Log(string.format("config.lua: %s must be from %s to %s; the default %s is used.", name,
                    tostring(limit[1]), tostring(limit[2]), tostring(default)))
            else
                settings[name] = value
            end
        end
    end
    return settings
end

-- One line for the log: every setting, sorted by name.
local function Describe(settings)
    local names = {}
    for name in pairs(settings) do
        names[#names + 1] = name
    end
    table.sort(names)
    local parts = {}
    for i, name in ipairs(names) do
        parts[i] = name .. "=" .. tostring(settings[name])
    end
    return table.concat(parts, ", ")
end

Log(VERSION .. " loaded.")
local Settings = ReadSettings()
Log("Settings: " .. Describe(Settings))

-- Real time in seconds (wall time on Windows).
local function Now()
    return os.clock()
end

local function LogDusk(message)
    if not Settings.LogDusk then
        return
    end
    duskLogs = duskLogs + 1
    if duskLogs <= MAX_DUSK_LOGS then
        Log(string.format("%.3f %s", Now(), message))
    elseif duskLogs == MAX_DUSK_LOGS + 1 then
        Log("LogDusk: " .. MAX_DUSK_LOGS .. " lines reached; no more until the next game start.")
    end
end

local function Valid(object)
    if object == nil then
        return false
    end
    local ok, valid = pcall(function()
        return object:IsValid()
    end)
    return ok and valid == true
end

local function ClassName(object)
    local ok, name = pcall(function()
        return object:GetClass():GetFName():ToString()
    end)
    return ok and name or "?"
end

-- A hook parameter comes as a UE4SS RemoteUnrealParam: :get() gives the value.
local function Get(param)
    local ok, value = pcall(function()
        return param:get()
    end)
    if ok then
        return value
    end
    return param
end

-- The day counter.
local controller = nil
local library = nil
local lastDeath = -1000
local lastPawnKey = nil

local function ControlledPawn()
    if not Valid(controller) then
        controller = UEHelpers.GetPlayerController()
    end
    if not Valid(controller) then
        return nil
    end
    local pawn = controller.Pawn
    return Valid(pawn) and pawn or nil
end

local function Difficulty(pawn)
    if not Valid(library) then
        library = StaticFindObject(LIBRARY_PATH)
        if not Valid(library) then
            library = nil
            return nil
        end
    end
    local ok, mode = pcall(function()
        return library:GetDiffcultMode(pawn)
    end)
    return ok and tonumber(mode) or nil
end

local function Days(pawn)
    local ok, days = pcall(function()
        return pawn.RemainingDays
    end)
    return ok and tonumber(days) or nil
end

local function Health(pawn)
    local ok, health = pcall(function()
        return pawn.AttributeSetBase.Health.CurrentValue
    end)
    return ok and tonumber(health) or nil
end

local function KeepDays()
    local pawn = ControlledPawn()
    if pawn == nil then
        return
    end
    local days = Days(pawn)
    local health = Health(pawn)
    if days == nil or health == nil then
        return
    end
    local mode = Difficulty(pawn)
    local key = ClassName(pawn) .. "/" .. tostring(mode)
    if key ~= lastPawnKey then
        lastPawnKey = key
        LogDusk(string.format("player %s: difficulty %s, %d days left, health %.1f", ClassName(pawn), tostring(mode),
            days, health))
    end
    if mode ~= NIGHTMARE then
        return
    end
    local now = Now()
    if health <= 0 then
        if now - lastDeath > 1 then
            LogDusk(string.format("death with %d days left: the counter stays untouched", days))
        end
        lastDeath = now
        return
    end
    if now - lastDeath < DEATH_HOLD_SECONDS or days == DAYS_ALIVE then
        return
    end
    local ok = pcall(function()
        pawn.RemainingDays = DAYS_ALIVE
    end)
    local refreshed = pcall(function()
        pawn:RefreshMaterialParam()
    end)
    LogDusk(string.format("days left %d -> %d%s%s", days, DAYS_ALIVE, ok and "" or " (write failed)",
        refreshed and "" or " (RefreshMaterialParam failed)"))
end

-- 66 Days from the first game: the flag is set right before the C++ check and gets its old value back after it.
local unlockRestore = nil
local unlockAnswers = 0

local function RestoreUnlock()
    local restore = unlockRestore
    unlockRestore = nil
    if restore ~= nil and Valid(restore.system) then
        pcall(function()
            restore.system.bCanSelectNightMare = restore.value
        end)
    end
end

local function HookUnlock()
    local ok, err = pcall(RegisterHook, CAN_SELECT_PATH, function(context)
        local done, problem = pcall(function()
            local system = Get(context)
            if system.bCanSelectNightMare ~= false then
                return
            end
            unlockRestore = { system = system, value = false }
            system.bCanSelectNightMare = true
            ExecuteInGameThread(RestoreUnlock)
            unlockAnswers = unlockAnswers + 1
            if unlockAnswers <= 3 then
                LogDusk("66 Days check: answered yes (the flag goes back to locked right after)")
            end
        end)
        if not done then
            LogError("Error in the 66 Days check: " .. tostring(problem))
        end
    end, function()
        pcall(RestoreUnlock)
    end)
    if not ok then
        LogError("66 Days check not hooked: " .. tostring(err):match("^[^\n]*"))
    end
end

-- The texts.
local busy = false
local textCheckUntil = -1000

local function MakeText(text)
    return UEHelpers.GetKismetTextLibrary():Conv_StringToText(text)
end

local function TextOf(block)
    local ok, text = pcall(function()
        return block:GetText():ToString()
    end)
    return ok and text or nil
end

-- The new text for an English original, or nil.
local function Replacement(text)
    if text == nil then
        return nil
    end
    return TEXTS[text]
end

local function WidgetName(widget)
    local ok, name = pcall(function()
        return widget:GetFName():ToString()
    end)
    return ok and name or ""
end

local function FixButton(button, how)
    if busy or not Valid(button) then
        return
    end
    local ok, text = pcall(function()
        return TextOf(button.ButtonTextBlock)
    end)
    if not ok or text == nil then
        return
    end
    local rule = BUTTONS[text]
    local new = nil
    if rule ~= nil then
        if WidgetName(button) == rule.name then
            new = rule.to
        end
    else
        new = Replacement(text)
    end
    if new == nil then
        return
    end
    busy = true
    local done = pcall(function()
        button:SetButtonText(MakeText(new))
    end)
    busy = false
    LogDusk(string.format("text (%s): '%s' -> '%s'%s", how, text, new, done and "" or " (SetButtonText failed)"))
end

local function FixText(block, how)
    if busy or not Valid(block) then
        return
    end
    local text = TextOf(block)
    local new = Replacement(text)
    if new == nil then
        return
    end
    busy = true
    local way = "SetPBZFormatText"
    local done = pcall(function()
        block:SetPBZFormatText(MakeText(new))
    end)
    if not done or TextOf(block) ~= new then
        way = "SetText"
        done = pcall(function()
            block:SetText(MakeText(new))
        end)
    end
    busy = false
    LogDusk(string.format("text (%s, %s): '%s' -> '%s'%s", how, way, text, new, done and "" or " (failed)"))
end

-- A hook that changes the text after the game's function: in UE4SS's post callback, or queued from the first
-- callback (which runs before the function). opensCheck: the two menu setters open the backup check
-- (the check runs FindAllOf, so it runs only while a menu is open).
local function HookText(path, fix, opensCheck)
    local ok, err = pcall(RegisterHook, path, function(context)
        if busy then
            return
        end
        if opensCheck then
            textCheckUntil = Now() + TEXT_CHECK_SECONDS
        end
        local object = Get(context)
        ExecuteInGameThread(function()
            local done, problem = pcall(fix, object, "queued")
            if not done then
                LogError("Error in a text change: " .. tostring(problem))
            end
        end)
    end, function(context)
        if busy then
            return
        end
        local done, problem = pcall(fix, Get(context), "post")
        if not done then
            LogError("Error in a text change: " .. tostring(problem))
        end
    end)
    if not ok then
        LogError("Text hook not set (" .. path .. "): " .. tostring(err):match("^[^\n]*"))
    end
end

local function CheckTexts()
    if Now() > textCheckUntil then
        return
    end
    for _, menu in ipairs(MENUS) do
        for _, widget in ipairs(FindAllOf(menu.widget) or {}) do
            if Valid(widget) then
                for _, name in ipairs(menu.buttons) do
                    FixButton(widget[name], "check")
                end
                for _, name in ipairs(menu.texts) do
                    FixText(widget[name], "check")
                end
            end
        end
    end
end

-- Dialogs (AsyncAction_ShowConfirmation, for example the settings' "Difficulty cannot be changed ..."): the game
-- makes them from a text key in C++, which no hook reaches. Before Activate (the first callback) the texts of the
-- action's Descriptor change, so the dialog is built with them; after Activate the open dialog's two text fields are
-- checked as a backup (the dialog is set up inside Activate).
local function FixDescriptor(action)
    if busy or not Valid(action) or ClassName(action) ~= CONFIRMATION_CLASS then
        return false
    end
    local descriptor = action.Descriptor
    if not Valid(descriptor) then
        return false
    end
    for _, field in ipairs({ "Header", "Body" }) do
        local ok, text = pcall(function()
            return descriptor[field]:ToString()
        end)
        local new = ok and Replacement(text) or nil
        if new ~= nil then
            local done, err = pcall(function()
                descriptor[field] = MakeText(new)
            end)
            LogDusk(string.format("dialog %s (descriptor): '%s' -> '%s'%s", field, text, new,
                done and "" or (" (failed: " .. tostring(err) .. ")")))
        end
    end
    return true
end

local function FixDialogs(how)
    for _, dialog in ipairs(FindAllOf(DIALOG_CLASS) or {}) do
        if Valid(dialog) then
            for _, field in ipairs({ "Text_Title", "RichText_Description" }) do
                local block = dialog[field]
                if Valid(block) then
                    local text = TextOf(block)
                    local new = Replacement(text)
                    if new ~= nil then
                        busy = true
                        local done = pcall(function()
                            block:SetText(MakeText(new))
                        end)
                        busy = false
                        LogDusk(string.format("dialog %s (%s): '%s' -> '%s'%s", field, how, text, new,
                            done and "" or " (SetText failed)"))
                    end
                end
            end
        end
    end
end

local function HookDialogs()
    local confirmation = false
    local ok, err = pcall(RegisterHook, ACTIVATE_PATH, function(context)
        local done, problem = pcall(function()
            confirmation = FixDescriptor(Get(context))
        end)
        if not done then
            LogError("Error in a dialog text: " .. tostring(problem))
        end
    end, function()
        if not confirmation then
            return
        end
        confirmation = false
        local done, problem = pcall(FixDialogs, "after Activate")
        if not done then
            LogError("Error in a dialog text: " .. tostring(problem))
        end
    end)
    if not ok then
        LogError("Dialog hook not set: " .. tostring(err):match("^[^\n]*"))
    end
end

HookUnlock()
HookText(SET_BUTTON_PATH, FixButton, true)
HookText(SET_KEY_PATH, FixText, true)
HookDialogs()

RegisterLoadMapPostHook(function()
    controller = nil
    lastDeath = -1000
    lastPawnKey = nil
end)

LoopAsync(CHECK_INTERVAL_MS, function()
    ExecuteInGameThread(function()
        local ok, err = pcall(KeepDays)
        if not ok then
            LogError("Error in the day counter: " .. tostring(err))
        end
    end)
    -- false keeps the loop running.
    return false
end)

LoopAsync(TEXT_CHECK_MS, function()
    ExecuteInGameThread(function()
        local ok, err = pcall(CheckTexts)
        if not ok then
            LogError("Error in the text check: " .. tostring(err))
        end
    end)
    return false
end)
