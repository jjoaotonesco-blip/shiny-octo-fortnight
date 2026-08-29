#!/usr/bin/env python3
from pathlib import Path
import re
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else 'stk-code')


def must_replace(s: str, old: str, new: str, label: str, count: int = 1) -> str:
    actual = s.count(old)
    if actual < count:
        raise RuntimeError(f'{label}: expected at least {count}, got {actual}')
    return s.replace(old, new, count)


# -----------------------------------------------------------------------------
# Xbox Ball Cam state + persistent camera behavior
hpp = root / 'src/karts/controller/local_player_controller.hpp'
s = hpp.read_text(encoding='utf-8')
s = must_replace(
    s,
    '    bool           m_soccer_ball_cam;\n    bool           m_soccer_boost_pressed;',
    '    bool           m_soccer_ball_cam;\n'
    '    bool           m_soccer_ball_cam_button_pressed;\n'
    '    bool           m_soccer_boost_pressed;',
    'local_player_controller.hpp Ball Cam button state',
)
hpp.write_text(s, encoding='utf-8')
print('GAMEPLAY FIX', hpp)

cpp = root / 'src/karts/controller/local_player_controller.cpp'
s = cpp.read_text(encoding='utf-8')
old_init = '    m_soccer_ball_cam = false;\n    m_soccer_boost_pressed = false;'
if s.count(old_init) != 2:
    raise RuntimeError(
        'local_player_controller.cpp: expected constructor+reset Ball Cam init anchors, '
        f'got {s.count(old_init)}'
    )
s = s.replace(
    old_init,
    '    m_soccer_ball_cam = false;\n'
    '    m_soccer_ball_cam_button_pressed = false;\n'
    '    m_soccer_boost_pressed = false;'
)

new_toggle = '''    // Default Xbox Y is PA_RESCUE. In soccer it toggles persistent Ball Cam.
    // Edge-triggered so holding Y cannot toggle it multiple times.
    if (action == PA_RESCUE && dynamic_cast<SoccerWorld*>(World::getWorld()))
    {
        const bool pressed = value != 0;
        if (dry_run) return pressed != m_soccer_ball_cam_button_pressed;
        if (pressed && !m_soccer_ball_cam_button_pressed)
        {
            m_soccer_ball_cam = !m_soccer_ball_cam;
#ifndef SERVER_ONLY
            if (!GUIEngine::isNoGraphics() && m_camera_index >= 0)
            {
                Camera* camera = Camera::getCamera(m_camera_index);
                if (camera && camera->getType() != Camera::CM_TYPE_END)
                    camera->setMode(m_soccer_ball_cam
                        ? Camera::CM_SOCCER_BALL : Camera::CM_NORMAL);
            }
#endif
        }
        m_soccer_ball_cam_button_pressed = pressed;
        return true;
    }

'''

patterns = [
    re.compile(
        r'    // In soccer,.*?(?=    // Pause race doesn\'t need to be sent to server)',
        re.S,
    ),
    re.compile(
        r'    if \([^\n]*PA_(?:LOOK_BACK|RESCUE)[^\n]*SoccerWorld[^\n]*\)\n'
        r'    \{.*?(?=    // Pause race doesn\'t need to be sent to server)',
        re.S,
    ),
]
match = None
for pat in patterns:
    match = pat.search(s)
    if match:
        break
if not match:
    pos = s.find('PA_RESCUE')
    excerpt = s[max(0, pos - 700):pos + 1400] if pos >= 0 else 'PA_RESCUE not found'
    print(excerpt)
    raise RuntimeError('local_player_controller.cpp: could not locate soccer Ball Cam toggle block')
s = s[:match.start()] + new_toggle + s[match.end():]

start = s.find('        const bool rocket_soccer = dynamic_cast<SoccerWorld*>(World::getWorld()) != NULL;')
end = s.find('        if (m_sky_particles_emitter)', start)
if start < 0 or end < 0:
    raise RuntimeError('local_player_controller.cpp: could not locate soccer camera update guard')
new_guard = '''        const bool rocket_soccer = dynamic_cast<SoccerWorld*>(World::getWorld()) != NULL;
        if (!rocket_soccer && (m_controls->getLookBack() || (UserConfigParams::m_reverse_look_threshold > 0 &&
            m_kart->getSpeed() < -UserConfigParams::m_reverse_look_threshold)))
            camera->setMode(Camera::CM_REVERSE);
        else if (rocket_soccer)
        {
            // Ball Cam stays active until Y is pressed again.
            if (m_soccer_ball_cam && camera->getMode() != Camera::CM_SOCCER_BALL)
                camera->setMode(Camera::CM_SOCCER_BALL);
            else if (!m_soccer_ball_cam && camera->getMode() == Camera::CM_SOCCER_BALL)
                camera->setMode(Camera::CM_NORMAL);
        }
        else if (camera->getMode() == Camera::CM_REVERSE)
        {
            camera->setMode(Camera::CM_NORMAL);
        }
'''
s = s[:start] + new_guard + s[end:]
cpp.write_text(s, encoding='utf-8')
print('GAMEPLAY FIX', cpp)

cam = root / 'src/graphics/camera/camera_normal.cpp'
s = cam.read_text(encoding='utf-8')
start = s.find('                // Camera stays behind the kart relative to the ball')
if start < 0:
    start = s.find('                const float camera_distance = std::min(')
end_marker = '                wanted_target = ball_pos + Vec3(0.0f, 0.25f, 0.0f);\n'
end = s.find(end_marker, start)
if start < 0 or end < 0:
    raise RuntimeError('camera_normal.cpp: could not locate old Ball Cam position block')
end += len(end_marker)
new_camera = '''                // Rocket-style Ball Cam: stay close behind the kart itself,
                // then rotate the view toward the ball.
                Vec3 kart_forward = m_kart->getSmoothedTrans().getBasis().getColumn(2);
                kart_forward.setY(0.0f);
                if (kart_forward.length2() < 0.001f)
                    kart_forward = flat_to_ball;
                kart_forward.normalize();
                const float camera_distance = std::min(4.0f,
                    std::max(2.8f, 2.85f + ball_distance * 0.012f));
                wanted_position = kart_pos - kart_forward * camera_distance
                    + Vec3(0.0f, 1.45f, 0.0f);
                wanted_target = ball_pos + Vec3(0.0f, 0.20f, 0.0f);
'''
s = s[:start] + new_camera + s[end:]
cam.write_text(s, encoding='utf-8')
print('GAMEPLAY FIX', cam)

soccer = root / 'src/modes/soccer_world.cpp'
s = soccer.read_text(encoding='utf-8')
for pattern, replacement, label in [
    (r'body->applyCentralImpulse\(up \* \(mass \* [0-9.]+f\)\);',
     'body->applyCentralImpulse(up * (mass * 10.8f));', 'higher first jump'),
    (r'body->applyCentralImpulse\(dir \* \(mass \* [0-9.]+f\)\);',
     'body->applyCentralImpulse(dir * (mass * 9.6f));', 'stronger second jump'),
    (r'if \(speed < [0-9.]+f\)',
     'if (speed < 50.0f)', 'higher boost speed gate'),
    (r'const float accel = grounded \? [0-9.]+f : [0-9.]+f;',
     'const float accel = grounded ? 24.0f : 45.0f;', 'stronger aerial boost'),
]:
    s, n = re.subn(pattern, replacement, s, count=1)
    if n != 1:
        raise RuntimeError(f'soccer_world.cpp {label}: expected 1 structural match, got {n}')

air_marker = s.find('// Air steering:')
if air_marker < 0:
    raise RuntimeError('soccer_world.cpp: Air steering marker not found')
air_start = s.find('            const float steer = controls.getSteer();', air_marker)
air_end = s.find('            if (body->getAngularVelocity().length() > 5.5f)', air_start)
if air_start < 0 or air_end < 0:
    raise RuntimeError('soccer_world.cpp: aerial control block boundaries not found')
air_block = '''            const float steer = controls.getSteer();
            const float pitch = controls.getAccel() - (controls.getBrake() ? 1.0f : 0.0f);
            const float roll = controls.getSkidControl() == KartControl::SC_NONE ? 0.0f : steer;
            // Xbox left stick back -> nose UP; forward -> nose DOWN.
            // X (drift) + left/right adds air roll, Rocket-League style.
            body->applyTorque((up * (-steer * 11.5f) + right * (pitch * 26.0f) +
                               forward * (-roll * 24.0f)) * mass);
'''
s = s[:air_start] + air_block + s[air_end:]

soccer.write_text(s, encoding='utf-8')
print('GAMEPLAY FIX', soccer)

print('Xbox defaults confirmed: A=Fire/jump, B=Nitro/boost, X=Drift/air-roll, Y=Rescue/BallCam, LB=LookBack')
