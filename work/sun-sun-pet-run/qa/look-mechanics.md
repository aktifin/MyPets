# Sun-Sun look mechanics

Sun-Sun is a rounded robotic red panda with physical glossy eyeballs, a separate helmet-like head, articulated ears, a rigid torso, short planted legs, and a segmented tail. Looking around should read as attention, not as whole-sprite rotation.

## Anchors and motion order

- Keep both feet, the lower torso, body scale, and baseline fixed in every direction.
- The glossy eyeballs lead by rotating as complete eye surfaces; irises, pupils, highlights, eyelids, and eye rims stay physically coherent.
- The head follows with a restrained yaw or pitch. The upper torso may follow by a few degrees, but the whole sprite never tilts or spins.
- Ear fins follow the head with a very small lag. The segmented tail remains attached and mostly stable, with only a subtle continuous counter-shift.
- No prop, new object, detached effect, shadow, label, arrow, or guide mark may appear.

## Cardinal pose families

- `000 up`: pupils and eye globes aim upward; upper eyelids lift slightly; chin rises a little; more underside of the muzzle is visible; ears open upward. Both body sides remain balanced.
- `090 screen-right`: pupils, nose tip, muzzle, and head turn toward the viewer's right edge; the pet's left cheek becomes more visible and the right cheek compresses slightly; the right ear is more side-on. Tail stays attached and lags subtly left.
- `180 down`: pupils and eye globes aim downward; upper eyelids lower slightly; chin tucks; more forehead shell is visible; ears relax outward. Both body sides remain balanced.
- `270 screen-left`: pupils, nose tip, muzzle, and head turn toward the viewer's left edge; the pet's right cheek becomes more visible and the left cheek compresses slightly; the left ear is more side-on. Tail stays attached and lags subtly right.

## Interpolation and motion budget

Treat the sixteen poses as one continuous clockwise loop. Each 22.5-degree step moves the eye globes, head, ears, muzzle landmarks, and tail by roughly the same visual amount. No adjacent pair may introduce a scale jump, baseline jump, side flip, sudden tail relocation, or larger head bend than its neighbors. `157.5 -> 180`, `337.5 -> 000`, and the row boundary must be as smooth as every other step.
