# UAM Corridor Simulator v2.0

Web-based UAM (Urban Air Mobility) corridor congestion simulation and visualization tool.

## Features

- **Real-time Simulation**: 1-lane straight corridor with automatic separation enforcement
- **Congestion Analysis**: Segment-based, KDE density, and vehicle-centric congestion metrics
- **Interactive Controls**: Spawn/delete aircraft, adjust speeds, real-time parameter tuning
- **Apple-style UI**: Dark/light theme, frosted glass panels, smooth Canvas rendering
- **WebSocket Communication**: Real-time state synchronization via FastAPI + WebSocket

## Architecture

```
uam-corridor-sim/
├── backend/
│   ├── server.py          # FastAPI + WebSocket server
│   └── simulation.py      # Core simulation engine
├── frontend/
│   ├── index.html          # Main page
│   ├── css/style.css       # Apple-style theme
│   └── js/
│       ├── renderer.js     # HTML5 Canvas renderer
│       └── app.js          # App controller + WebSocket client
├── requirements.txt
└── README.md
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run server
cd backend
python server.py
```

Open `http://localhost:8000` in your browser.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Space | Play / Pause |
| N | Spawn aircraft |
| R | Reset simulation |
| . | Single step |
| Delete | Delete selected aircraft |

## Congestion Models

### Segment-based (구간 기반)
- Divides corridor into segments of configurable length
- Computes overflow + TTI excess weighted score
- Color-coded: Green → Yellow → Orange → Red

### KDE Density (공간 밀집도)
- Kernel Density Estimation with anisotropic Gaussian
- σ∥ (parallel) and σ⊥ (perpendicular) configurable

### Vehicle-centric (기체 기반)
- Per-aircraft congestion: c = ρ̂ × max(D_avg, R)
- Forward propagation ratio R for delay cascade detection
