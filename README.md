# Glass Brick Lights

A browser-based controller for a 6-column by 10-row grid of glass-brick lights. The project includes the single-page interface in `index.html` and a small Python server in `main.py` for trying the interface locally without LED hardware.

## Requirements

- Python 3.9 or newer
- A modern browser with JavaScript enabled

The local simulator uses only Python's standard library; no packages need to be installed.

## Run the local simulator

From this directory, start the server:

```bash
python main.py
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000) in a browser. The server binds to the local machine only. Stop it with `Ctrl+C`.

Opening `index.html` directly as a file is not the recommended way to use the page: its controls make requests to the web server at the page's origin.

## Using the interface

- **Setup:** Select a color, then click a cell to set it. Use **Erase**, **Clear**, **Fill**, **Random**, or **Rainbow** to change the grid.
- **Animations:** Choose an animation from the Animations tab.
- **Tetris:** Start a game and use the on-screen controls or the arrow keys. The left/right arrows move, the down arrow moves down, the up arrow rotates, and Space drops the piece.
- **Turn access:** Press **PLAY** to claim the shared turn. The simulator grants one browser session a turn at a time for up to 120 seconds. The page retains its session ID in browser `localStorage`.

## Files

- `main.py` serves `index.html` and provides a lightweight, in-memory HTTP simulator for the grid and turn state.
- `index.html` contains the responsive interface, styles, and client-side JavaScript for grid editing, animations, and Tetris.

## Simulator limitations

`main.py` is a development simulator, not Pico firmware and not a hardware driver. Its grid state exists only in server memory and is reset when the process restarts. It reports all six columns as connected.

The simulator supports turn management and basic grid operations (individual cells, clear, fill, random, and rainbow). Animation requests are acknowledged without playing an animation. Tetris gameplay runs in the browser, but its board synchronization uses the `/gridset` endpoint, which the simulator does not provide; syncing Tetris to physical lights requires a compatible backend. Physical LED output requires separate hardware-specific firmware or a server implementation.
