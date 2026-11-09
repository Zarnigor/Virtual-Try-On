# avatar-prep

Removes the background and normalizes avatar/body photos to the 600x1200 canvas.

```
pyenv local 3.11.9            # if you use pyenv
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python prep.py ./photos ./output
```
First run downloads the segmentation model (about 170 MB).
Check every result by eye: the model sometimes eats thin hands or hair. Hands must not touch the body.
Then mark landmarks with the landmark editor (see ../landmark-editor-prototype).
