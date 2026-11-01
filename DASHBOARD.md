# EdgeVault - Dashboard + fake hub (Siddharth's part)

## Run it (two terminals)

Terminal 1 - fake hub (pretends to be the 4 cameras):

    cd hub
    pip install fastapi "uvicorn[standard]"
    python server.py

Terminal 2 - dashboard:

    cd dashboard
    npm install
    npm run dev

Open http://localhost:5173

## Demo buttons
- Trigger Intruder: Cam 1 sees a person -> asks peers for bids -> sends clip to cheapest.
- Trigger Disk Full: Cam 1 storage jumps to 95%. Do this BEFORE the intruder.
- Toggle Cam 3 offline: then trigger intruder again to show re-routing to Cam 4.
- Reset: restore everything.

The bundled hallway videos generate clearly labeled demo annotations in the agent
reasoning log as playback reaches the empty-scene, person-entry, and walking
segments. These are time-based annotations, not live computer-vision inference.
The simulation buttons remain separate from the video annotations.

## Contract (share with the team)
Hub -> dashboard over WebSocket ws://localhost:9000/ws, messages `{kind, data}`:
- `state`: {cams: {cam1: {name, online, used_mb, capacity_mb, last_score, status}}, ledger: {cam1: 100.0}, stored_for_others: {cam1: 0}}
- `event`: {ts, cam, type, msg, score}   type = perceive|reason|bid|transfer|evict|compress|audit|alert|offline
- `history`: list of events (sent once on connect)

Real cameras send events to the hub with:
    POST http://localhost:9000/event   {"cam":"cam1","type":"perceive","msg":"...","score":0.9}

## Swapping fake for real
The dashboard never changes. Only hub/server.py gets replaced by real camera events:
keep the `/ws` and `/state` endpoints, and call `emit()` whenever a camera reports something.
