"""Offline test of Scripts/main.lua with lupa (Lua 5.4) and small mocks of UE4SS and the game.

The mocks stand in for the UE4SS functions that the script uses (LoopAsync, ExecuteInGameThread as a queue that runs
after the current call, RegisterHook with a first and a post callback, RegisterLoadMapPostHook, StaticFindObject,
FindAllOf, UEHelpers) and for the game: a clock (os.clock), the player controller and pawn (RemainingDays, health,
RefreshMaterialParam), the function library's GetDiffcultMode, the game system's bCanSelectNightMare flag, and the
two menus with their buttons (SetButtonText) and descriptions (they ignore SetText, like PBZCommonLocText). The game
calls a hooked native function like UE4SS: first callback, then the function, then (when the test says so) the post
callback.

The settings checks run main.lua with the shipped Scripts/config.lua and with the files a player may have instead:
none, an empty or older one, a broken one, one without a table, one with values of the wrong type, and one with a
setting the mod does not know. main.lua must start without an error in each case, and a setting that the file does
not give must keep its default. The shipped config.lua must hold exactly the defaults of main.lua.

Usage:
    python tests/test_main.py        (needs lupa: python -m pip install lupa)

Exit code: 0 = all checks passed, 1 = a check failed.
"""

import json
import sys
import tempfile
from pathlib import Path

from lupa import lua54

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "src" / "phantombladezero_mortaldusk" / "Scripts" / "main.lua"
CONFIG = MAIN.parent / "config.lua"

CAN_SELECT = "/Script/ProjectPBZ.PBZGameSystem:CanSelectNightMare"
SET_BUTTON = "/Script/ProjectPBZ.PBZButtonBase:SetButtonText"
SET_KEY = "/Script/ProjectPBZ.PBZCommonLocText:SetTextByLocKey"
SET_FORMAT = "/Script/ProjectPBZ.PBZCommonLocText:SetPBZFormatText"
ACTIVATE = "/Script/Engine.BlueprintAsyncActionBase:Activate"
TIMERS = 2

OLD_15 = "66 days only. Every step could be your last."
OLD_16 = ('Same difficulty as "Hellwalker," but deaths are limited to 66 times. Unlocked after completing the game on '
          'any other difficulty.')
NEW_15 = "One life. Your first death is your last."
NEW_16 = 'Same difficulty as "Hellwalker," but a single death ends the run.'

MOCKS = r"""
LOG = {}
print = function(...) LOG[#LOG + 1] = table.concat({...}, "") end

CLOCK = 0
os.clock = function() return CLOCK end

local FNameMeta = { __index = { ToString = function(self) return self.text end } }
function FName(text) return setmetatable({ text = text }, FNameMeta) end
local function T(s) return { ToString = function() return s end } end

local ObjectMeta = { __index = { IsValid = function(self) return self.valid end } }
function OBJECT(fields)
    fields = fields or {}
    if fields.valid == nil then fields.valid = true end
    return setmetatable(fields, ObjectMeta)
end
function NAMED(className, fields)
    local object = OBJECT(fields)
    object.GetClass = function() return { GetFName = function() return FName(className) end } end
    return object
end

REFRESHES = 0
function PLAYER(days, health)
    return NAMED("BP_Renewal_Hun_Young_C", { RemainingDays = days,
        AttributeSetBase = { Health = { CurrentValue = health } },
        RefreshMaterialParam = function(self) REFRESHES = REFRESHES + 1 end })
end
PAWN = PLAYER(66, 850)
CONTROLLER = OBJECT({ Pawn = PAWN })
MODE = 4
LIBRARY = OBJECT({ GetDiffcultMode = function(self, context) return MODE end })
SYSTEM = OBJECT({ bCanSelectNightMare = false })

-- Buttons and descriptions like the game's: a description ignores SetText (PBZCommonLocText).
BUTTON_CALLS = 0
function BLOCK(text)
    local block = NAMED("PBZCommonLocText", { txt = text })
    block.GetText = function(self) return T(self.txt) end
    block.SetText = function(self, t) end
    block.SetPBZFormatText = function(self, t) self.txt = t.s end
    return block
end
function BUTTON(text, name)
    local button = NAMED("W_MenuButton_V2_SelectedVersion_C", { ButtonTextBlock = BLOCK(text) })
    button.GetFName = function() return FName(name or "") end
    -- The game's function, called by the mod through UE4SS: the hooks fire around it.
    button.SetButtonText = function(self, t)
        BUTTON_CALLS = BUTTON_CALLS + 1
        GAME_CALL(SET_BUTTON_PATH, self, function() self.ButtonTextBlock.txt = t.s end, POST)
    end
    return button
end
START = OBJECT({ ContinueGame = BUTTON("CONTINUE", "ContinueGame") })
DIFF = OBJECT({ Nightmare = BUTTON("66 DAYS", "Nightmare"), Desc1 = BLOCK(""), Desc2 = BLOCK("") })
OTHER = BUTTON("CONTINUE", "Button_Continue")
-- A confirmation dialog (PBZConfirmationScreen) and the action that builds it from its Descriptor.
function FT(s) return { s = s, ToString = function(self) return self.s end } end
DIALOG = NAMED("W_ConfirmationDefault_C", { Text_Title = BLOCK(""), RichText_Description = BLOCK("") })
DIALOG.RichText_Description.SetText = function(self, t) self.txt = t.s end
-- locked: the Descriptor's text fields cannot be written (the mod must then change the open dialog).
function ACTION(body, locked)
    local fields = { Header = FT(""), Body = FT(body) }
    local descriptor = setmetatable({}, {
        __index = function(t, k)
            if k == "IsValid" then return function() return true end end
            return fields[k]
        end,
        __newindex = function(t, k, v)
            if locked then error("FText property is read only") end
            fields[k] = v
        end })
    return NAMED("AsyncAction_ShowConfirmation", { Descriptor = descriptor })
end
-- Activate: the dialog shows the Descriptor's texts (it is set up inside Activate).
function GAME_ACTIVATE(action, withPost)
    GAME_CALL("/Script/Engine.BlueprintAsyncActionBase:Activate", action, function()
        if action.Descriptor then
            DIALOG.Text_Title.txt = action.Descriptor.Header.s
            DIALOG.RichText_Description.txt = action.Descriptor.Body.s
        end
    end, withPost)
end

FIND_ALL = 0
MENUS_OPEN = true
function FindAllOf(name)
    FIND_ALL = FIND_ALL + 1
    if not MENUS_OPEN then return nil end
    if name == "WB_StartMenu_V2_C" then return { START } end
    if name == "WB_DifficultySelect_V2_C" then return { DIFF } end
    if name == "PBZConfirmationScreen" then return { DIALOG } end
    return nil
end
function StaticFindObject(path)
    if path == "/Script/ProjectPBZ.Default__PBZBlueprintFunctionLibrary" then return LIBRARY end
    return OBJECT({ valid = false })
end

-- RegisterHook with a first callback (runs before the function) and a post callback.
HOOKS = {}
function RegisterHook(path, first, post)
    HOOKS[path] = { first = first, post = post }
    return 1, 2
end
local function Param(value) return { get = function() return value end } end
POST = false
SET_BUTTON_PATH = "/Script/ProjectPBZ.PBZButtonBase:SetButtonText"
-- A call of a hooked native function: first callback, the function, then the post callback when withPost.
function GAME_CALL(path, object, body, withPost)
    local hook = HOOKS[path]
    if hook then hook.first(Param(object)) end
    local result = body()
    if hook and withPost and hook.post then hook.post(Param(object)) end
    return result
end
function GAME_SET_BUTTON(button, text, withPost)
    GAME_CALL(SET_BUTTON_PATH, button, function() button.ButtonTextBlock.txt = text end, withPost)
end
function GAME_SET_FORMAT(block, text, withPost)
    GAME_CALL("/Script/ProjectPBZ.PBZCommonLocText:SetPBZFormatText", block, function() block.txt = text end, withPost)
end
function GAME_SET_KEY(block, text, withPost)
    GAME_CALL("/Script/ProjectPBZ.PBZCommonLocText:SetTextByLocKey", block, function() block.txt = text end, withPost)
end
-- The menu's 66 Days check: the C++ function reads the flag.
function GAME_CHECK_UNLOCK(withPost)
    return GAME_CALL("/Script/ProjectPBZ.PBZGameSystem:CanSelectNightMare", SYSTEM,
        function() return SYSTEM.bCanSelectNightMare end, withPost)
end

MAP_HOOKS = {}
function RegisterLoadMapPostHook(callback) MAP_HOOKS[#MAP_HOOKS + 1] = callback end

-- ExecuteInGameThread queues; FLUSH runs the queue (the next tick).
QUEUE = {}
function ExecuteInGameThread(callback) QUEUE[#QUEUE + 1] = callback end
function FLUSH()
    local rounds = 0
    while #QUEUE > 0 and rounds < 20 do
        local queued = QUEUE
        QUEUE = {}
        for i = 1, #queued do queued[i]() end
        rounds = rounds + 1
    end
end
LOOPS = {}
function LoopAsync(ms, callback) LOOPS[#LOOPS + 1] = callback end
function TICK() for i = 1, #LOOPS do LOOPS[i]() end FLUSH() end

package.preload["UEHelpers"] = function()
    return {
        GetPlayerController = function() return CONTROLLER end,
        GetKismetTextLibrary = function()
            return { Conv_StringToText = function(self, s) return FT(s) end }
        end,
    }
end

function DESCRIBE(t)
    local names = {}
    for name in pairs(t) do names[#names + 1] = tostring(name) end
    table.sort(names)
    local parts = {}
    for i, name in ipairs(names) do parts[i] = name .. "=" .. tostring(t[name]) end
    return table.concat(parts, ", ")
end
"""

PLAYER_CONFIGS = [
    ("no config.lua", None, "No config.lua"),
    ("an empty or older config.lua", "return {}\n", None),
    ("a broken config.lua", "return {\n    LogDusk =\n", "config.lua not read"),
    ("a config.lua without a table", "-- nothing here\n", "does not return a table"),
    ("a config.lua with wrong types", "wrong types", "must be a"),
    ("a config.lua with an unknown setting", "return { NoSuchSetting = 1 }\n", "unknown setting NoSuchSetting"),
]


def lua_path(path: Path) -> str:
    return "[[" + path.as_posix() + "]]"


def lua_long(text: str) -> str:
    """A Lua long string that holds text exactly (no escapes)."""
    return "[==[" + text + "]==]"


def run(config_folder: Path, ticks: int = 3):
    """Runs main.lua with require("config") reading config.lua in config_folder, and its timers. A Lua error that
    stops main.lua becomes an "Error" line in the log, so the checks fail instead of the test."""
    lua = lua54.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(MOCKS)
    lua.execute(f'package.path = {lua_path(config_folder)} .. "/?.lua"; package.cpath = ""')
    g = lua.globals()
    try:
        lua.execute(MAIN.read_text(encoding="utf-8"))
        for _ in range(ticks):
            lua.execute("TICK()")
    except lua54.LuaError as error:
        g.LOG[len(g.LOG) + 1] = "Error: main.lua stopped: " + str(error).splitlines()[0]
    return lua, g, [g.LOG[i].rstrip() for i in range(1, len(g.LOG) + 1)]


def settings_line(log):
    lines = [line.split("] Settings: ", 1)[1] for line in log if "] Settings: " in line]
    return lines[0] if len(lines) == 1 else None


def all_lines(g):
    return [g.LOG[i].rstrip() for i in range(1, len(g.LOG) + 1)]


def main() -> None:
    version = json.loads((ROOT / "mod.json").read_text(encoding="utf-8"))["version"]
    failures = []

    def check(condition, text):
        print(("ok    " if condition else "FAIL  ") + text)
        if not condition:
            failures.append(text)

    # The mod as players get it, with the shipped config.lua.
    lua, g, log = run(CONFIG.parent)
    for line in log:
        print("      log: " + line)
    check(len(g.LOOPS) == TIMERS, f"{TIMERS} LoopAsync timers (the day counter, the text check)")
    check(len(g.MAP_HOOKS) == 1, "one map load hook")
    check(len(list(g.HOOKS.keys())) == 4
          and all(g.HOOKS[p] is not None for p in (CAN_SELECT, SET_BUTTON, SET_KEY, ACTIVATE)),
          "four hooks at start: the 66 Days check, the two menu text setters, Activate (dialogs)")
    check(any(f"{version} loaded." in line for line in log), f"load line with the version {version} of mod.json")
    check(not any("Error" in line for line in log), "no error line after three timer runs")
    check(not any("config.lua" in line for line in log), "the shipped config.lua is read without a warning")
    shipped = lua.eval(f"DESCRIBE(dofile({lua_path(CONFIG)}))")
    check(settings_line(log) == shipped, "the settings line shows the values of the shipped config.lua")

    with tempfile.TemporaryDirectory() as temp:
        folders = {}
        extra = [("LogDusk on", "return { LogDusk = true }\n", None),
                 ("LogDusk off", "return { LogDusk = false }\n", None)]
        for case, content, _ in PLAYER_CONFIGS + extra:
            folder = Path(temp) / str(len(folders))
            folder.mkdir()
            if content == "wrong types":
                content = lua.eval(f"""(function()
                    local lines = {{}}
                    for name, value in pairs(dofile({lua_path(CONFIG)})) do
                        lines[#lines + 1] = string.format("    [%q] = %s,", name, type(value) == "string" and "0" or '"wrong"')
                    end
                    return "return {{\\n" .. table.concat(lines, "\\n") .. "\\n}}\\n"
                end)()""")
            if content is not None:
                (folder / "config.lua").write_text(content, encoding="utf-8")
            folders[case] = folder

        defaults = settings_line(run(folders["an empty or older config.lua"])[2])
        check(defaults == shipped, f"config.lua ships exactly the defaults of main.lua ({defaults})")

        for case, _, expected in PLAYER_CONFIGS:
            _, g2, log2 = run(folders[case])
            fine = (len(g2.LOOPS) == TIMERS and settings_line(log2) == defaults
                    and not any("Error" in line for line in log2))
            if expected is None:
                fine = fine and not any("config.lua" in line for line in log2)
            else:
                fine = fine and any(expected in line for line in log2)
            if case == "a config.lua with wrong types":
                count = len(list(lua.eval(f"dofile({lua_path(CONFIG)})").keys()))
                fine = fine and sum("must be a " in line for line in log2) == count
            check(fine, f"{case}: starts, every setting at its default"
                  + (f", logs '{expected}'" if expected else ", no warning"))
            if not fine:
                for line in log2:
                    print("      log: " + line)

        # The day counter.
        lua, g, _ = run(folders["LogDusk on"])

        def lines_after(code):
            mark = len(g.LOG)
            lua.execute(code)
            return [g.LOG[i].rstrip() for i in range(mark + 1, len(g.LOG) + 1)]

        log = all_lines(g)
        check(g.PAWN.RemainingDays == 1 and g.REFRESHES >= 1
              and any("player BP_Renewal_Hun_Young_C: difficulty 4, 66 days left" in line for line in log)
              and any("days left 66 -> 1" in line for line in log),
              "66 Days: the counter goes from 66 to 1, the game's RefreshMaterialParam is called")
        lines = lines_after("CLOCK = 10 PAWN.RemainingDays = 0 TICK()")
        check(g.PAWN.RemainingDays == 1 and any("days left 0 -> 1" in line for line in lines),
              "a story event that takes the last day while the player is alive: back to 1")
        lines = lines_after("CLOCK = 20 PAWN.AttributeSetBase.Health.CurrentValue = 0 PAWN.RemainingDays = 0 TICK() "
                            "CLOCK = 21 TICK()")
        check(g.PAWN.RemainingDays == 0 and sum("death with 0 days left" in line for line in lines) == 1,
              "a death: the counter stays at 0 (the game ends the run), logged once")
        lua.execute("CLOCK = 26 PAWN.AttributeSetBase.Health.CurrentValue = 850 TICK()")
        held = g.PAWN.RemainingDays
        lua.execute("CLOCK = 42 TICK()")
        check(held == 0 and g.PAWN.RemainingDays == 1,
              "health back without the end (a game path without it): untouched for 20 s, then 1 again")
        lua.execute("CLOCK = 50 PAWN.AttributeSetBase.Health.CurrentValue = 0 PAWN.RemainingDays = 0 TICK() "
                    "MAP_HOOKS[1]() PAWN = PLAYER(66, 850) CONTROLLER.Pawn = PAWN CLOCK = 52 TICK()")
        check(g.PAWN.RemainingDays == 1, "after a map load (the run restarted) a new player gets 1 day at once")
        lines = lines_after("MODE = 3 PAWN = PLAYER(66, 850) CONTROLLER.Pawn = PAWN CLOCK = 60 TICK() TICK()")
        check(g.PAWN.RemainingDays == 66 and any("difficulty 3, 66 days left" in line for line in lines),
              "another difficulty: the counter stays the game's")
        lua.execute("MODE = 4 CONTROLLER.Pawn = OBJECT({ valid = false }) CLOCK = 70 TICK()")
        check(not any("Error" in line for line in all_lines(g)), "no player (a menu): no error")

        # 66 Days from the first game.
        mark = len(g.LOG)
        answer = lua.eval("GAME_CHECK_UNLOCK(false)")
        flag_during = g.SYSTEM.bCanSelectNightMare
        lua.execute("FLUSH()")
        lines = [g.LOG[i].rstrip() for i in range(mark + 1, len(g.LOG) + 1)]
        check(answer is True and flag_during is True and g.SYSTEM.bCanSelectNightMare is False
              and any("66 Days check: answered yes" in line for line in lines),
              "the 66 Days check answers yes; the flag is locked again right after (queued)")
        answer = lua.eval("GAME_CHECK_UNLOCK(true)")
        check(answer is True and g.SYSTEM.bCanSelectNightMare is False,
              "with UE4SS's post callback the flag is locked again in the same call")
        lua.execute("SYSTEM.bCanSelectNightMare = true")
        answer = lua.eval("GAME_CHECK_UNLOCK(false)")
        lua.execute("FLUSH()")
        check(answer is True and g.SYSTEM.bCanSelectNightMare is True,
              "a profile that unlocked 66 Days in the game keeps its flag")

        # The texts.
        lua.execute("GAME_SET_BUTTON(START.ContinueGame, 'CONTINUE', false)")
        before = g.START.ContinueGame.ButtonTextBlock.txt
        lua.execute("FLUSH()")
        check(before == "CONTINUE" and g.START.ContinueGame.ButtonTextBlock.txt == "ONE DEATH IS ALL IT TAKES"
              and g.BUTTON_CALLS == 1,
              "main menu: CONTINUE changed after the game's call (queued), one call of SetButtonText, no loop")
        lua.execute("POST = true BUTTON_CALLS = 0 GAME_SET_BUTTON(DIFF.Nightmare, '66 DAYS', true)")
        check(g.DIFF.Nightmare.ButtonTextBlock.txt == "MORTAL DUSK" and g.BUTTON_CALLS == 1,
              "with the post callback the 66 Days name changes in the same call, no loop")
        lua.execute("FLUSH()")
        lua.execute(f"GAME_SET_KEY(DIFF.Desc1, {OLD_15!r}, true) GAME_SET_KEY(DIFF.Desc2, {OLD_16!r}, false) FLUSH()")
        check(g.DIFF.Desc1.txt == NEW_15 and g.DIFF.Desc2.txt == NEW_16,
              "the two 66 Days descriptions change through SetPBZFormatText (SetText is ignored)")
        lua.execute("GAME_SET_KEY(DIFF.Desc1, 'The ultimate trial.', true) "
                    "GAME_SET_BUTTON(START.ContinueGame, \"LET'S DIE AGAIN!\", true) FLUSH()")
        check(g.DIFF.Desc1.txt == "The ultimate trial." and g.START.ContinueGame.ButtonTextBlock.txt == "LET'S DIE AGAIN!",
              "other texts stay; with Let's Die Again its text stays (only the exact English original changes)")

        lua.execute("POST = true GAME_SET_BUTTON(OTHER, 'CONTINUE', true) FLUSH()")
        check(g.OTHER.ButtonTextBlock.txt == "CONTINUE", "another CONTINUE button of the game stays (only ContinueGame)")

        # 1.3 (the user's choice "let us stay simple"): the save lists keep the game's texts (no SetPBZFormatText hook).
        lua.execute("CLOCK = 90 B = BLOCK('') GAME_SET_FORMAT(B, 'Difficulty: 66 DAYS', true) FLUSH()")
        check(g.B.txt == "Difficulty: 66 DAYS" and g.HOOKS[SET_FORMAT] is None,
              "the save lists stay as the game has them (no SetPBZFormatText hook)")

        # The dialogs: the two difficulty refusals.
        old_13 = "Cannot switch to 66 Days after starting a game."
        lua.execute(f"A = ACTION({lua_long(old_13)}, false) GAME_ACTIVATE(A, true)")
        check(g.DIALOG.RichText_Description.txt == "Cannot switch to Mortal Dusk after starting a game.",
              "the dialog 'Cannot switch to 66 Days ...' says Mortal Dusk")
        old_11 = "Difficulty cannot be changed after starting a game on 66 Days."
        new_11 = "Difficulty cannot be changed after starting a game on Mortal Dusk."
        lua.execute(f"A = ACTION({lua_long(old_11)}, false) GAME_ACTIVATE(A, true)")
        check(g.DIALOG.RichText_Description.txt == new_11 and g.A.Descriptor.Body.s == new_11,
              "a dialog: the Descriptor changes before Activate, the dialog shows the new text at once")
        lua.execute(f"DIALOG.RichText_Description.txt = '' A = ACTION({lua_long(old_11)}, true) GAME_ACTIVATE(A, true)")
        check(g.DIALOG.RichText_Description.txt == new_11,
              "when the Descriptor cannot be written, the open dialog's text changes after Activate")
        fill = g.FIND_ALL
        lua.execute("W = NAMED('AbilityAsync_WaitGameplayEvent', {}) GAME_ACTIVATE(W, true)")
        check(g.FIND_ALL == fill, "another async action's Activate: nothing, no FindAllOf")

        # The backup check: only for 3 s after a hook fired.
        lua.execute("CLOCK = 100 GAME_SET_KEY(DIFF.Desc2, 'x', true) FLUSH() DIFF.Desc2.txt = " + repr(OLD_16)
                    + " CLOCK = 101 TICK()")
        check(g.DIFF.Desc2.txt == NEW_16, "within 3 s after a hook the check changes a text that the hooks missed")
        lua.execute(f"CLOCK = 110 FIND_ALL = 0 DIFF.Desc2.txt = {OLD_16!r} TICK() TICK() TICK()")
        check(g.FIND_ALL == 0 and g.DIFF.Desc2.txt == OLD_16, "during play (no hook for 3 s) the check runs no FindAllOf")
        check(not any("Error" in line for line in all_lines(g)), "no error line in the whole run")

        # LogDusk off: no lines, the counter still works.
        lua4, g4, log4 = run(folders["LogDusk off"])
        check(g4.PAWN.RemainingDays == 1 and not any("days left" in line for line in log4),
              "LogDusk = false: the counter goes to 1 without log lines")

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
