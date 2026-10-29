# Mortal Dusk

On the 66 Days difficulty a single death ends the run, and 66 Days is open from the first game.

A [UE4SS](https://github.com/UE4SS-RE/RE-UE4SS) Lua mod for Phantom Blade Zero (Unreal Engine 5.7), made with
game version `CL-301524_JKS-17219` and UE4SS `v3.0.1-1183-gcdbc0b66`. This README is for developers; what the mod does and
how to install it are in [openmods.md](openmods.md), the mod page on [openmods](https://openmods.nexus).

## How it works

- **Days:** the 66 Days difficulty (`EDifficultMode::NightMare` = 4, read with the static
  `UPBZBlueprintFunctionLibrary:GetDiffcultMode(pawn)`) counts the days left in the player's Blueprint variable
  `RemainingDays` (66 at the start, saved per slot). A death takes one (`RenewalPlayer.js` `PushWidgetAndChangeData`,
  `Clamp(Days - 1, 0, 66)`); at 0 the death screen sets `IsFinishDead` and `GameModeBuild.triggerBadEnding()` ends the
  run (the bad-ending level; the save slot later restarts the run from its start). Every 250 ms the script sets
  `RemainingDays` to 1 while the player's health is above 0, and calls the player's `RefreshMaterialParam()` as the
  game does after its own changes. Story events take a day too (`GameplayEvent.Dead.ChangeDaysLeft`); the next check
  sets it back. While the health is 0, and 20 s after it, the counter stays untouched, so the end is never cancelled.
  Other difficulties: no change.
- **66 Days from the first game:** the difficulty menu's Blueprint function `CanSelectNightmare` calls the C++
  `UPBZGameSystem:CanSelectNightMare`, which reads `bCanSelectNightMare` (saved for the account). A UE4SS hook on a
  native function runs before it: the script sets the flag in memory there, and gives it its old value back right
  after (UE4SS's post callback, else queued with `ExecuteInGameThread`), so the game never saves it. The mod
  `phantombladezero_66daysunlocked` did the same in the menu's JavaScript.
- **Texts at runtime** (no `Game.locres` copy, so no conflict with a text mod such as `phantombladezero_letsdieagain`):
  the FText from `KismetTextLibrary:Conv_StringToText`; buttons (`UPBZButtonBase`) through `SetButtonText`, the
  difficulty menu's descriptions (`UPBZCommonLocText`, which ignores `SetText`) through `SetPBZFormatText`. The texts:
  the main menu's "CONTINUE" (only the button `ContinueGame`), the difficulty menu's entry and descriptions
  (`UI_SelectDifficutly_09`, `_15`, `_16`) and the difficulty refusal dialogs (`_11`, `_13`); only the exact English
  originals change (`TEXTS`), so other languages keep the game's texts. The save lists and the settings' value switch
  keep "66 DAYS" (the user's choice: "let us stay simple"; 1.2 tried them through more hooks). The menus set the texts
  through the C++ `PBZButtonBase:SetButtonText` and `PBZCommonLocText:SetTextByLocKey`; the hooks on them run before
  the function, so the change waits until after it (UE4SS's post callback did it in the game tests), and a guard stops
  the script's own calls from firing the hooks again (a test without it looped until Lua stopped it). Dialogs
  (`AsyncAction_ShowConfirmation...ByKey`) get their text in C++ from a key: a hook on
  `BlueprintAsyncActionBase:Activate` changes `Descriptor.Header` / `Body` before the dialog is built (UE4SS writes
  the FText, game test of 1.1), and after `Activate` checks the open dialog's `Text_Title` / `RichText_Description`
  (`UPBZConfirmationScreen`). For 3 s after a menu setter fired, a check every 500 ms looks at `WB_StartMenu_V2_C`
  and `WB_DifficultySelect_V2_C` as a backup; during play no `FindAllOf` runs.
- **Log (`LogDusk`):** the difficulty and days of each player, each change of the counter, each death, each answer of
  the 66 Days check, each text change.

## Deploy and test

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy.ps1     # copy the mod folder into the game's ue4ss\Mods
python tests\test_main.py                                 # offline test of main.lua (needs lupa)
```

`deploy.ps1` copies `src\phantombladezero_mortaldusk\` to `<game folder>\platform\steam\ue4ss\Mods\phantombladezero_mortaldusk\`. The game
folder is `$env:UE5_GAMES_DIR\PBZ`; `-GameDir` or `-ModsDir` override it. The mod folder holds
`enabled.txt`, so UE4SS starts it without an entry in `mods.txt`. An existing `Scripts\config.lua` in the game stays
(the tester's settings); `-ResetConfig` copies the shipped one. UE4SS loads Lua mods at game start. The mod writes
its lines into `ue4ss\UE4SS.log`, for example `[Mortal Dusk] 1.0 loaded.`

`tests\test_main.py` runs `main.lua` in Lua 5.4 ([lupa](https://pypi.org/project/lupa/)) with mocks of the UE4SS
functions that the script uses and of the game (the player with its days and health, the difficulty, the 66 Days
flag, the two menus). Hooked functions run like in UE4SS: first callback, the function, post callback; queued calls
run after the current one. It finds syntax and logic errors before a game start.

Versioning: every change raises the second number (1.0 -> 1.1) in `mod.json` and in `main.lua`:
`python scripts\bump_version.py`.

## Settings

`Scripts/config.lua` holds the player's settings, `DEFAULTS` in `main.lua` every setting with its default. Players and
mod managers keep their own `config.lua` across updates, so a new `main.lua` can meet an older file: a setting that
the file lacks, or has with another type, keeps its default, and the log says so (`ReadSettings`). Add each setting to
both files with the same value, and read it only from `Settings`, never as `config.X or default` (for a true/false
setting, `false or true` is true). `tests\test_main.py` checks that `config.lua` ships exactly the defaults, and runs
`main.lua` with a missing, empty, broken and wrong `config.lua`.

## Project layout

```
src/phantombladezero_mortaldusk/   The UE4SS mod folder: Scripts/main.lua, Scripts/config.lua, enabled.txt
tests/test_main.py    Offline test of main.lua with mocks of UE4SS and the game
docs/                 Cover and screenshots
scripts/              bump_version.py
deploy.ps1            Copies the mod folder into the game's ue4ss\Mods
mod.json              Name, version, game, engine and UE4SS version
```

## License

MIT, see [LICENSE](LICENSE).
