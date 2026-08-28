#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else 'stk-code')

def patch(rel, replacements):
    p = root / rel
    s = p.read_text(encoding='utf-8')
    for old, new, label in replacements:
        if old not in s:
            raise RuntimeError(f'{rel}: missing anchor: {label}')
        s = s.replace(old, new, 1)
    p.write_text(s, encoding='utf-8')
    print('GAMEPLAY FIX', rel)

patch('src/karts/controller/local_player_controller.hpp', [
    ('    bool           m_soccer_ball_cam;\n    bool           m_soccer_boost_pressed;',
     '    bool           m_soccer_ball_cam;\n    bool           m_soccer_ball_cam_button_pressed;\n    bool           m_soccer_boost_pressed;',
     'ball cam edge state'),
])

p = root / 'src/karts/controller/local_player_controller.cpp'
s = p.read_text(encoding='utf-8')
old = '    m_soccer_ball_cam = false;\n    m_soccer_boost_pressed = false;'
if s.count(old) != 2:
    raise RuntimeError(f'local_player_controller.cpp: expected 2 init/reset anchors, got {s.count(old)}')
s = s.replace(old, '    m_soccer_ball_cam = false;\n    m_soccer_ball_cam_button_pressed = false;\n    m_soccer_boost_pressed = false;')
old_toggle = '''    // In soccer, LOOK BACK becomes a local Ball Cam toggle. It is not
    // sent over the network because camera state is purely local.
    if ((action == PA_LOOK_BACK || action == PA_RESCUE) && dynamic_cast<SoccerWorld*>(World::getWorld()))
    {
        if (dry_run) return value != 0;
        if (value != 0)
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
        return true;
    }
'''
new_toggle = '''    // Default Xbox Y is PA_RESCUE. In soccer it toggles persistent Ball Cam.
    // Use an edge state so holding Y cannot toggle the camera repeatedly.
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
if old_toggle not in s:
    raise RuntimeError('local_player_controller.cpp: missing old ball cam toggle')
s = s.replace(old_toggle, new_toggle, 1)
old_guard = '''        if (!rocket_soccer && (m_controls->getLookBack() || (UserConfigParams::m_reverse_look_threshold > 0 &&
            m_kart->getSpeed() < -UserConfigParams::m_reverse_look_threshold)))
            camera->setMode(Camera::CM_REVERSE);
        else if (!rocket_soccer)
        {
            if (camera->getMode() == Camera::CM_REVERSE)
            {
                camera->setMode(Camera::CM_NORMAL);
            }
        }
'''
new_guard = '''        if (!rocket_soccer && (m_controls->getLookBack() || (UserConfigParams::m_reverse_look_threshold > 0 &&
            m_kart->getSpeed() < -UserConfigParams::m_reverse_look_threshold)))
            camera->setMode(Camera::CM_REVERSE);
        else if (rocket_soccer)
        {
            // Keep Ball Cam active until Y is explicitly pressed again.
            if (m_soccer_ball_cam && camera->getMode() != Camera::CM_SOCCER_BALL)
                camera->setMode(Camera::CM_SOCCER_BALL);
            else if (!m_soccer_ball_cam && camera->getMode() == Camera::CM_SOCCER_BALL)
                camera->setMode(Camera::CM_NORMAL);
        }
        else
        {
            if (camera->getMode() == Camera::CM_REVERSE)
            {
                camera->setMode(Camera::CM_NORMAL);
            }
        }
'''
if old_guard not in s:
    raise RuntimeError('local_player_controller.cpp: missing camera update guard')
s = s.replace(old_guard, new_guard, 1)
p.write_text(s, encoding='utf-8')
print('GAMEPLAY FIX src/karts/controller/local_player_controller.cpp')

patch('src/graphics/camera/camera_normal.cpp', [
    ('''                // Camera stays behind the kart relative to the ball, while
                // looking directly at the ball (Rocket League Ball Cam feel).
                const float camera_distance = std::min(6.5f,
                    std::max(4.2f, 4.2f + ball_distance * 0.035f));
                wanted_position = kart_pos - flat_to_ball * camera_distance
                    + Vec3(0.0f, 1.85f, 0.0f);
                wanted_target = ball_pos + Vec3(0.0f, 0.25f, 0.0f);
''',
     '''                // Keep Ball Cam close behind the KART, then aim at the ball.
                // This behaves more like Rocket League than orbiting behind the ball line.
                Vec3 kart_forward = m_kart->getSmoothedTrans().getBasis().getColumn(2);
                kart_forward.setY(0.0f);
                if (kart_forward.length2() < 0.001f) kart_forward = flat_to_ball;
                kart_forward.normalize();
                const float camera_distance = std::min(4.0f,
                    std::max(2.8f, 2.85f + ball_distance * 0.012f));
                wanted_position = kart_pos - kart_forward * camera_distance
                    + Vec3(0.0f, 1.45f, 0.0f);
                wanted_target = ball_pos + Vec3(0.0f, 0.20f, 0.0f);
''',
     'closer ball cam'),
])

patch('src/modes/soccer_world.cpp', [
    ('body->applyCentralImpulse(up * (mass * 8.2f));',
     'body->applyCentralImpulse(up * (mass * 10.8f));', 'higher first jump'),
    ('body->applyCentralImpulse(dir * (mass * 8.6f));',
     'body->applyCentralImpulse(dir * (mass * 9.6f));', 'stronger second jump'),
    ('up * (-steer * 9.5f) + right * (pitch * 18.0f) +',
     'up * (-steer * 11.5f) + right * (pitch * 26.0f) +', 'stronger aerial pitch/yaw'),
    ('forward * (-roll * 20.0f)) * mass);',
     'forward * (-roll * 24.0f)) * mass);', 'stronger air roll'),
    ('if (speed < 42.0f)', 'if (speed < 50.0f)', 'higher boost speed gate'),
    ('const float accel = grounded ? 22.0f : 32.0f;',
     'const float accel = grounded ? 24.0f : 45.0f;', 'stronger aerial boost'),
])

print('Xbox defaults used by STK: A=Fire/jump, B=Nitro/boost, X=Drift/air-roll, Y=Rescue/BallCam, LB=LookBack')
