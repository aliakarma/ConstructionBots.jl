# Installs the project's exact package versions, points PyCall at the Python in ENV["PYTHON"] (the one with rvo2) and
# registers the Jupyter kernel. Called by setup.ps1 and setup.sh.
using Pkg

Pkg.activate(dirname(@__DIR__))
Pkg.instantiate()
Pkg.build("PyCall")

# IJulia goes in the global environment so that the project's Project.toml and Manifest.toml stay unchanged.
Pkg.activate()
Pkg.add("IJulia")
using IJulia
IJulia.installkernel("Julia", "--project=@.")
