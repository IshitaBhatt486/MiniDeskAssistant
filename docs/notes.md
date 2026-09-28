- A motor encoder is a sensor that tells your controller what the motor shaft is actually doing.
- Without an encoder, you might tell a motor:

"Rotate at 50% power."

But you don't actually know whether it:

rotated 100°
rotated 80°
got stuck
slipped
is rotating too fast
is rotating too slowly
- With an encoder, you can measure things like:

position
speed
direction
sometimes acceleration
- Motor = muscles
Encoder = eyes/ears telling the controller what the muscles actually did
- without encoder- You command a PWM duty cycle and hope the motor behaves as expected. This is called roughly open-loop control.
- encoder corrects the motor's rotation- closed loop control
- the encoder has two signals -quadrature signals- because A and B are phase-shifted, you can determine:

how much the shaft rotated
which direction it rotated
A leads B → clockwise

B leads A → counter-clockwise
