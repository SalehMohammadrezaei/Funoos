# Gallery mapping: scenes → experiments

Version 1.3.0 organises the gallery as **27 experiment cards** holding all **48
presets**. Scene keys (the stable identifiers used by saved setups, favourites,
recent items, clips and tests) are unchanged; each now belongs to exactly one
experiment (`flowzoo/catalog.py: EXPERIMENTS`, checked by `catalog.check_experiments()`
in `tests/test_cases.py`).

| experiment (card) | presets (scene keys) |
|---|---|
| Cylinder wake | lbm_cylinder_steady (Steady wake, Re 40), lbm_cylinder (Vortex shedding, Re 180) |
| Airfoil lift | lbm_airfoil_neg (−14°), lbm_airfoil_zero (0° baseline), lbm_airfoil (+14°) |
| Cycling and drafting | lbm_cyclist (Single rider), lbm_peloton (Two riders) |
| Flow around text | lbm_name |
| Car silhouette | lbm_f1 |
| Porous flow | porous_phi60 (Default sample), porous_connectivity (Different arrangement), porous_aniso (Directional flow) |
| Rising smoke | ns_smoke |
| Rayleigh–Taylor instability | ns_rt_single (Single mode), ns_rt (Multiple modes) |
| Candle flame | ns_flame |
| Heated-layer convection | ns_rb_conduction (Conduction baseline), ns_rb (Convection cells), ns_rb_vigorous (Vigorous convection) |
| Chimney plume | ns_chimney_calm (Calm air), ns_chimney (Moderate crosswind), ns_chimney_strong (Strong crosswind) |
| Sod shock tube | euler_sod |
| Open-air blast | euler_blast |
| Blast and obstacles | euler_city (Held obstacles), euler_city_erosion (Experimental erosion) |
| Shock–bubble interaction | euler_bubble (Light bubble), euler_bubble_heavy (Heavy bubble), euler_twin (Twin bubbles) |
| Still-water baseline | sph_rest |
| Dam break | sph_dam |
| Water-blob impact | sph_drop |
| Sloshing tank | sph_slosh |
| Pouring | sph_pour |
| Wave tank | sph_waves |
| Floating hull | sph_ship_still (Still water), sph_ship (Waves) |
| Kelvin–Helmholtz instability | spec_kh |
| Decaying turbulence | spec_decay |
| Taylor–Green vortex | spec_tg |
| Dye transport | mix_diffusion (Diffusion only), mix_stir (Stirring only), mix_bands (Stirring with diffusion) |
| Gray–Scott patterns | rd_spots, rd_stripes (Stripes/coral), rd_maze (Labyrinth), rd_mitosis (Replication), rd_custom (Custom) |

Stored data migrates on first launch: favourites (`funoos.favs`, scene keys) become
`funoos.favs2` (`{experimentId: sceneKey}`) so a favourite reopens on the preset that
was favourited; recents keep their scene key alongside the experiment id. Saved setup
files reference scene keys and load unchanged. Search matches preset names and labels
but lists the parent experiment once.
