# Setting up the ConstructionBots Experiment Lab notebook

**Most people do not need this guide.** Double-click `notebooks\start_notebook.bat` (Windows), or run
`sh notebooks/start_notebook.sh` (Linux). The first start performs every step below automatically, and later
starts open the notebook directly. Use this guide if the automatic setup stops with an error, or on macOS.

This guide installs everything needed to run `notebooks/ConstructionBots_Experiment_Lab.ipynb`.
It is written for **Windows 10/11** (the platform it was tested on) with notes for macOS/Linux.
You do this **once per computer**. Afterwards, running experiments needs no installation.

| Step | What | Needed for |
|---|---|---|
| 1 | Julia 1.10 and the repository's Julia packages | everything |
| 2 | LDraw Parts Library (LEGO part shapes) | everything |
| 3 | Python 3.7 environment with the **sisl fork of RVO2**, connected to Julia | **every** run (even with RVO2 switched off) |
| 4 | Jupyter kernel for Julia (IJulia) and VS Code | opening the notebook |
| 5 | Check the installation | |
| Optional | Gurobi licence | only the "Gurobi" solver |

Paths below use `C:\Users\<you>`; replace `<you>` with your Windows user name.

---

## Step 1 — Julia and the project packages

1. Install Julia with **juliaup**, the official installer: open PowerShell and run

   ```powershell
   winget install --id 9NJNWW8PVKMN -e -s msstore     # "Julia" from the Microsoft Store (juliaup)
   juliaup add 1.10
   juliaup default 1.10
   ```

   (Alternatively download the installer from <https://julialang.org/downloads/>.) The project was tested with
   Julia **1.10.12**. Close and reopen PowerShell, then check: `julia --version`.

   If `julia` is "not recognized", use the full path instead, e.g.
   `& "$env:USERPROFILE\.julia\juliaup\julia-1.10.12+0.x64.w64.mingw32\bin\julia.exe"`.

2. Install the repository's packages (this does **not** change `Project.toml`):

   ```powershell
   cd C:\Users\<you>\Documents\GitHub\ConstructionBots.jl
   julia --project=.
   ```

   and at the `julia>` prompt:

   ```julia
   using Pkg; Pkg.instantiate()
   ```

   This downloads the exact package versions the project needs, including the HiGHS and GLPK solvers.
   It can take 10–20 minutes the first time.

## Step 2 — LDraw Parts Library

ConstructionBots reads the shape of every LEGO part from the LDraw Parts Library. It is **not** included in
the repository (it is a separate ~450 MB download under the CC BY licence).

1. Download `complete.zip` from <https://library.ldraw.org/updates?latest> (the "Complete Library" link).
2. Unzip it so that you get `C:\Users\<you>\Documents\ldraw\parts` and `C:\Users\<you>\Documents\ldraw\p`.
   `Documents\ldraw` is the default location that the LDrawParser package looks in.
3. If you put it elsewhere, open the notebook's setup cell and set, for example,
   `LDRAW_LIBRARY_OVERRIDE = raw"D:\data\ldraw"`.

Do not copy the library into the repository.

## Step 3 — Python, RVO2 and PyCall

The simulator calls a **modified RVO2 collision-avoidance library** (with "dynamic priorities") through Python.
It must be the sisl fork <https://github.com/sisl/Python-RVO2>; the RVO2 package on PyPI lacks the functions the
simulator uses (`setAgentAlpha`). The simulator imports it for **every** run, even with RVO2 switched off.

### 3a. Create the Python 3.7 environment

With Anaconda or Miniconda installed, in an *Anaconda Prompt*:

```bat
conda create -p C:\Conda-Envs\lego_rvo2 python=3.7 -y
C:\Conda-Envs\lego_rvo2\python.exe -m pip install cython==0.29.36
```

> If `conda` itself fails with *"Unable to create process using ..."* (this happens when your Windows user
> folder contains a space), run it through Python instead:
> `"%USERPROFILE%\anaconda3\python.exe" -m conda create -p C:\Conda-Envs\lego_rvo2 python=3.7 -y`

### 3b. Build and install the sisl RVO2 module — choose ONE route

**Route A – official route (needs CMake and Microsoft C++ Build Tools, i.e. administrator rights).**
Install "Desktop development with C++" from the Visual Studio Installer and CMake (<https://cmake.org>), then
in a *x64 Native Tools Command Prompt for VS*:

```bat
git clone https://github.com/sisl/Python-RVO2.git C:\src\Python-RVO2
cd C:\src\Python-RVO2
C:\Conda-Envs\lego_rvo2\python.exe setup.py build
C:\Conda-Envs\lego_rvo2\python.exe setup.py install
```

**Route B – no administrator rights (the route used on the test computer).** This uses a MinGW-w64 compiler
from conda in a separate, throw-away environment and compiles the module directly. Run in PowerShell:

```powershell
# 1. Compiler in its own environment (short path: the old GCC fails on paths over 260 characters)
& "$env:USERPROFILE\anaconda3\python.exe" -m conda create -y -p C:\rvo2build\gcc -c msys2 m2w64-toolchain

# 2. Source code
git clone https://github.com/sisl/Python-RVO2.git C:\rvo2build\Python-RVO2
git -C C:\rvo2build\Python-RVO2 checkout 4174d402b4f229275f9f441709e8cf6aaece42c4
$env:PATH = "C:\rvo2build\gcc\Library\mingw-w64\bin;$env:PATH"
$PY  = "C:\Conda-Envs\lego_rvo2"
$SRC = "C:\rvo2build\Python-RVO2\src"

# 3. Cython -> C++, then compile one self-contained rvo2.pyd
& "$PY\python.exe" -m cython --cplus -3 -o C:\rvo2build\rvo2.cpp "$SRC\rvo2.pyx"
g++ -O2 -shared -std=c++11 -DMS_WIN64 -D_hypot=hypot -I"$PY\include" -I"$SRC" `
    C:\rvo2build\rvo2.cpp "$SRC\Agent.cpp" "$SRC\KdTree.cpp" "$SRC\Obstacle.cpp" "$SRC\RVOSimulator.cpp" `
    -static-libgcc -static-libstdc++ "-Wl,-Bstatic,--whole-archive" -lwinpthread "-Wl,--no-whole-archive,-Bdynamic" `
    -L"$PY" -lpython37 -o C:\rvo2build\rvo2.pyd

# 4. Install = copy one file into the environment, then test
Copy-Item C:\rvo2build\rvo2.pyd "$PY\Lib\site-packages\rvo2.pyd"
& "$PY\python.exe" -c "import rvo2; s = rvo2.PyRVOSimulator(0.025, 2., 5, 2., 1., .5, 4., (0., 0.)); a = s.addAgent((0., 0.)); s.setAgentAlpha(a, .5); print('rvo2 OK', rvo2.__file__)"
```

The resulting `rvo2.pyd` depends only on Windows system libraries and `python37.dll`. The folder
`C:\rvo2build` can be deleted afterwards. (On macOS/Linux use Route A: `python setup.py build install`
works with the system compiler and CMake.)

### 3c. Tell Julia which Python to use

Start Julia in the repository folder (`cd C:\Users\<you>\Documents\GitHub\ConstructionBots.jl`, then
`julia --project=.`) and type at the `julia>` prompt:

```julia
ENV["PYTHON"] = raw"C:\Conda-Envs\lego_rvo2\python.exe"
using Pkg; Pkg.build("PyCall")
```

Quit Julia (`exit()`), start it again with `julia --project=.`, and check:

```julia
using PyCall
PyCall.python                  # must show C:\Conda-Envs\lego_rvo2\python.exe
pyimport("rvo2").__file__      # must show ...\lego_rvo2\lib\site-packages\rvo2.pyd
```

## Step 4 — Jupyter kernel and VS Code

1. Install the Julia Jupyter kernel **into Julia's global environment** (not into the repository project):

   Start `julia` (without `--project`) and type:

   ```julia
   using Pkg; Pkg.activate(); Pkg.add("IJulia")
   ```

   This registers a kernel called **"Julia 1.10"**. The kernel starts Julia with `--project=@.`, so a notebook
   inside the repository automatically uses the repository's packages; the notebook's setup cell also
   activates the project explicitly.

2. In VS Code, install the **Jupyter** extension (`ms-toolsai.jupyter`). The **Julia** extension
   (`julialang.language-julia`) is optional but recommended.

3. Open the repository folder in VS Code (*File → Open Folder…*), open
   `notebooks/ConstructionBots_Experiment_Lab.ipynb`, click **Select Kernel** (top right) →
   **Jupyter Kernel…** → **Julia 1.10**.

   *Browser alternative:* from any Python with Jupyter installed, run `jupyter lab` in the repository folder,
   or at the `julia>` prompt: `using IJulia; jupyterlab(dir=pwd())`.

## Step 5 — Check the installation

Open the notebook, select the Julia 1.10 kernel, and run the **Setup** cell. Every line of the environment table
should say **OK** (a **WARNING** for Gurobi is normal without a licence). Then run the baseline experiment
(Sections 3 and 4). The first run takes 1–3 minutes because Julia compiles the code.

---

## Optional: Gurobi

Gurobi is **not needed**: HiGHS and GLPK are free and installed automatically. Use Gurobi only if you are
entitled to a licence.

* The `Gurobi` Julia package (already in `Project.toml`) installs the Gurobi 13.0 solver library through
  `Gurobi_jll`, under Gurobi's commercial EULA. **Without a licence it refuses to run**
  (`Gurobi Error 10009: No Gurobi license found`); the notebook then marks Gurobi as unavailable and skips it.
* **Academic licence (free for eligible users).** Students, faculty and staff of accredited degree-granting
  institutions can obtain free licences for non-commercial teaching and research:
  1. Register with your institutional e-mail at <https://www.gurobi.com/academia/academic-program-and-licenses/>.
  2. Request a **Named-User Academic** licence in the Gurobi User Portal (one person, one computer) or a
     **WLS Academic** licence (works on several computers via the internet).
  3. Named-User: download the Gurobi Optimizer (it contains the `grbgetkey` tool), and while connected to your
     **university network** run `grbgetkey <your-key>`; accept the default location
     (`C:\Users\<you>\gurobi.lic`). WLS: download the `gurobi.lic` file from the portal into `C:\Users\<you>\`.
  4. To keep the licence elsewhere, set the environment variable `GRB_LICENSE_FILE` to its full path.
  5. Restart the notebook kernel and run the setup cell; "Solver: Gurobi" should now say OK.
* A licence is **personal** (or bound to a machine / institution). Do **not** share licence files, put them in the
  repository, or paste licence keys into the notebook. Each lab member must obtain their own.
* Your licence must be valid for Gurobi **13.0**, the version installed here. Check current terms on Gurobi's site.
