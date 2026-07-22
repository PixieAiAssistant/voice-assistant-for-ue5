# 🧚 Pixie — AI Voice Assistant for Unreal Engine 5.8 & Windows

[![License](https://img.shields.io/badge/License-Proprietary-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2011%20%7C%2010-blue)](https://www.microsoft.com/windows)
[![Unreal Engine](https://img.shields.io/badge/Unreal%20Engine-5.8-8A2BE2)](https://www.unrealengine.com/)
[![Python](https://img.shields.io/badge/Python-3.11%2B-green)](https://www.python.org/)
[![Gemini](https://img.shields.io/badge/API-Gemini%20Live-FFD700)](https://deepmind.google/technologies/gemini/)

**Pixie** is a voice‑first AI assistant for game developers using **Unreal Engine 5.8**.  
It understands natural language, speaks back, and can **control Unreal Engine**, **automate Windows tasks**, and **write Python scripts** on the fly — all through voice commands.

---

## 🎥 Demo  
> *Coming soon – video walkthrough*

---

## ✨ Features

### 🎮 Unreal Engine 5.8 (via Python Remote Execution)

| Category | Tools |
|----------|-------|
| **Project Context** | `ue_get_project_context` – project name, map, GameMode, DefaultPawn, Content folder |
| **Level Navigation** | `ue_load_level`, `ue_save_level`, `ue_open_asset` – open any asset |
| **Search & Find** | `ue_list_actors` / `ue_find_actors` – locate actors on the level; `ue_list_assets` / `ue_find_assets` – find assets in Content Browser |
| **Inspection** | `ue_get_actor_info` (transform + properties), `ue_list_actor_components`, `ue_inspect_properties` (read property values) |
| **Actor Management** | `ue_spawn_actor`, `ue_delete_actor`, `ue_duplicate_actor`, `ue_teleport_actor`, `ue_set_actor_label`, `ue_attach_actor` |
| **Properties & Components** | `ue_set_property` (modify actor/component properties), `ue_set_component_property`, `ue_set_blueprint_property` |
| **Blueprint** | `ue_get_blueprint_info` (SCS components + Class Defaults), `ue_compile_blueprint` – compile Blueprint classes |
| **Camera Setup** | `ue_configure_camera` – first_person / third_person / fix_horizon / custom (SpringArm + Camera) |
| **Play In Editor** | `ue_play_in_editor` / `ue_stop_play_in_editor` |
| **Console Commands** | `ue_run_console` – safe console commands (dangerous ones filtered) |
| **Arbitrary Python** | `execute_unreal_python` – run any Python snippet inside UE 5.8 |
| **Script Library** | `ue_library_search` / `ue_library_load_snippet` – search and load ready‑to‑use Python recipes |

### 🖥️ Full Windows Control

- **Window focus** – switch to any app by partial title
- **Text input** – paste text into the active window (via clipboard)
- **Key combinations** – Win+R, Ctrl+Shift+Esc, Win+Space (change language), etc.
- **Window management** – minimise, close active window (gracefully or via taskkill), close by process name
- **File operations** – create, read, write, list files
- **Terminal** – execute cmd commands (fast with output, or GUI apps without blocking)

### 🎤 Voice Interface

- Uses **Gemini Live API** (real‑time streaming)
- Microphone input → voice → AI → voice response + actions
- Optional screen recording (0.2 FPS) for visual context
- Customisable voice and language (`config.json`)

---

## 🧠 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Pixie Agent (main.py)                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
│  │ Gemini   │  │ UE       │  │ Windows  │  │ Script      │ │
│  │ Live API │  │ Bridge   │  │ Tools    │  │ Library     │ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────────┘ │
└─────────────────────────────────────────────────────────────┘
         │              │              │              │
         ▼              ▼              ▼              ▼
┌─────────────┐  ┌─────────────┐  ┌──────────┐  ┌─────────────┐
│ Google      │  │ Unreal      │  │ Windows  │  │ UE 5.8      │
│ Gemini      │  │ Engine 5.8  │  │ OS API   │  │ Python      │
│ (Live)      │  │ (Remote Exec)│  │ (ctypes) │  │ Recipes     │
└─────────────┘  └─────────────┘  └──────────┘  └─────────────┘
```

### Core Modules

| File | Purpose |
|------|---------|
| `main.py` | Entry point, Gemini Live API, Windows tools, UE tool registration |
| `ue_bridge.py` | Bridge to UE via Remote Execution, safe argument handling, built‑in scripts |
| `ue_tools.py` | Extended UE tools: project, assets, Blueprint, camera, spawn/delete |
| `ue58_core.py` | Python helpers for UE 5.8 (common functions, components, camera, compilation) |
| `ue_script_library.py` | Local library of UE Python scripts (indexing, search, snippets) |
| `licensing.py` | License system (RSA + AES‑GCM), Free/Pro restrictions |
| `config_loader.py` | Loads `config.json`, Nuitka‑compatible |
| `gen_keys.py` | Generates RSA keys for signing licenses |
| `issue_license.py` | Issues license keys |
| `agent/server/license_server.py` | VPS server for online license verification |

---

## 🚀 Quick Start

### Requirements

- Windows 11 (or 10, 64‑bit)
- Python 3.11+
- Unreal Engine 5.8 (with Python Remote Execution enabled)
- Google Gemini API key (Gemini Live API)

### Installation

```bash
git clone https://github.com/dmanucharyan-del/pixie-ai.git
cd pixie-ai
pip install -r agent/requirements.txt
```

### Configuration

1. **Get Gemini API key**: [Google AI Studio](https://aistudio.google.com/app/apikey)
2. **Edit `agent/config.json`**:

   ```json
   {
     "gemini_api_key": "YOUR_API_KEY",
     "language": "en",
     "assistant_name": "Pixie",
     "voice_name": "Aoede",
     "ue_engine_path": "E:\\UE_5.8",
     "ue_project_path": "C:\\MyProject"
   }
   ```
3. **Enable Python Remote Execution** in UE 5.8:
   `Edit` → `Project Settings` → `Plugins` → `Python` → check `Enable Remote Execution`
4. **Run**:
   ```bash
   cd agent
   python main.py
   ```

---

## 🎯 Example Commands

### "Create a patrolling bot"

Pixie will automatically:
- Create a Blueprint class `BP_Enemy` (inherits from Character)
- Add components: SkeletalMesh, CapsuleCollision, AI Perception
- Set up Class Defaults (speed, health)
- Create a Blackboard with keys (`TargetActor`, `PatrolPoint`)
- Build a Behavior Tree (Patrol → Detect → Chase)
- Create an AI Controller
- Place the bot on the level

### "Configure camera to third‑person"

```python
ue_configure_camera(target="BP_Player", mode="third_person", 
                    apply_to="both", arm_length="400")
```

### "Find all StaticMeshActors and disable shadows"

```python
# Automatically searches and bulk‑updates bCastShadow property
```

---

## 📋 System Requirements

- **OS**: Windows 11 / 10 (x64)
- **Python**: 3.11 or higher
- **Unreal Engine**: 5.8 (with Python Remote Execution)
- **API**: Google Gemini Live API
- **Dependencies**: google-genai, pyaudio, mss, Pillow, pypdf, pyperclip, pyautogui, cryptography

---

## 🔒 Licensing

Pixie uses a two‑tier model:

- **Free**: Windows tools (window focus, text input, keys, files, terminal)
- **Pro**: All Unreal Engine tools (actors, Blueprint, camera, script library)

License verification is done locally (RSA signature + machine‑id) with optional online revocation check.

---

## ⚠️ Known Limitations

- ❌ Cannot edit Blueprint Event Graphs (Branch, Cast To, Delay nodes) – UE Python API limitation
- ❌ Cannot simulate mouse clicks – keyboard and Python inside UE only
- ❌ Video stream has 5‑10s latency (0.2 FPS)
- ❌ Dangerous console commands (open, changelevel, quit) are filtered
- ❌ C++ compilation requires UBT rebuild (1‑5 minutes per iteration)

---

## 🗺️ Roadmap

- [ ] **Support for Unreal Engine 5.7, 5.6, 5.5, 5.4** (backward compatibility)
- [ ] **Support for multiple AI APIs** – OpenAI (GPT‑4o), Anthropic (Claude), local LLMs (Ollama) – **without subscription lock‑in** (choose your own provider)
- [ ] Sequencer / Level Sequence – create cinematic cutscenes
- [ ] Niagara VFX – particle system creation & editing
- [ ] UMG / UI – build HUD and menus
- [ ] Gameplay Ability System – abilities, effects, cooldowns
- [ ] Geometry Script – procedural geometry generation
- [ ] Control Rig – procedural animation
- [ ] SmartObjects – AI interaction system
- [ ] MassEntity / ECS – large crowds of agents

---

## 🤝 Contributing

Pull requests are welcome! Please ensure your code:
- Follows the existing style
- Does not break backward compatibility
- Adds tests for new features

---

## 📄 License

Proprietary – see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgements

- [Google Gemini](https://deepmind.google/technologies/gemini/) – for the real‑time API
- [Unreal Engine](https://www.unrealengine.com/) – for the best game engine
- [python-remote-execution](https://github.com/EpicGames/UnrealEngine/tree/ue5-main/Engine/Plugins/PythonRemoteExecution) – for the Remote Execution protocol

---

*Made with ❤️ for game developers everywhere.*