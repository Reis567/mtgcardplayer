from django.shortcuts import render, redirect
from django.views import View
from django.http import JsonResponse
from django.conf import settings
from .models import PlayerProfile
import uuid


# Credenciais globais (pode ser movido para settings.py)
GLOBAL_USERNAME = 'mtgplayer'
GLOBAL_PASSWORD = 'commander2024'


class LoginView(View):
    """Pagina de login"""

    def get(self, request):
        return render(request, 'accounts/login.html')

    def post(self, request):
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')

        if username == GLOBAL_USERNAME and password == GLOBAL_PASSWORD:
            # Gerar um ID único para esta "sessão de aba"
            tab_id = uuid.uuid4().hex[:12]
            request.session[f'auth_{tab_id}'] = True
            return redirect(f'/profile/?tab={tab_id}')

        return render(request, 'accounts/login.html', {
            'error': 'Credenciais invalidas'
        })


class ProfileView(View):
    """Configurar perfil (nickname e avatar)"""

    def get(self, request):
        tab_id = request.GET.get('tab')
        if not tab_id or not request.session.get(f'auth_{tab_id}'):
            return redirect('login')

        return render(request, 'accounts/profile.html', {
            'profile': None,
            'tab_id': tab_id,
            'colors': ['#e94560', '#4ecdc4', '#45b7d1', '#96ceb4', '#ffeaa7', '#dfe6e9', '#fd79a8', '#6c5ce7']
        })

    def post(self, request):
        tab_id = request.POST.get('tab_id') or request.GET.get('tab')
        if not tab_id or not request.session.get(f'auth_{tab_id}'):
            return redirect('login')

        nickname = request.POST.get('nickname', '').strip()[:30]
        avatar_color = request.POST.get('avatar_color', '#e94560')

        if not nickname:
            return render(request, 'accounts/profile.html', {
                'error': 'Digite um nickname',
                'tab_id': tab_id,
                'colors': ['#e94560', '#4ecdc4', '#45b7d1', '#96ceb4', '#ffeaa7', '#dfe6e9', '#fd79a8', '#6c5ce7']
            })

        # Criar novo jogador com session_key única
        unique_key = f"tab_{tab_id}"

        profile = PlayerProfile.objects.create(
            session_key=unique_key,
            nickname=nickname,
            avatar_color=avatar_color
        )

        # Salvar o ID do jogador associado a este tab_id
        request.session[f'player_{tab_id}'] = str(profile.id)

        return redirect(f'/lobby/?tab={tab_id}')


class LogoutView(View):
    """Logout"""

    def get(self, request):
        tab_id = request.GET.get('tab')
        if tab_id:
            player_id = request.session.get(f'player_{tab_id}')
            if player_id:
                try:
                    profile = PlayerProfile.objects.get(id=player_id)
                    profile.is_online = False
                    profile.save()
                except PlayerProfile.DoesNotExist:
                    pass
                # Limpar apenas esta aba
                request.session.pop(f'player_{tab_id}', None)
                request.session.pop(f'auth_{tab_id}', None)
        else:
            # Logout completo
            request.session.flush()

        return redirect('login')


def get_current_player(request):
    """Helper para obter jogador atual da sessao/tab"""
    # Tentar pegar tab_id da URL
    tab_id = request.GET.get('tab') or request.POST.get('tab_id')

    print(f"[get_current_player] tab_id from request: {tab_id}")

    if tab_id:
        player_id = request.session.get(f'player_{tab_id}')
        print(f"[get_current_player] Got player_id from session with tab: {player_id}")
    else:
        # Fallback: procurar qualquer player_id na sessão
        player_id = None
        print(f"[get_current_player] No tab_id, searching session...")
        for key in request.session.keys():
            if key.startswith('player_'):
                player_id = request.session[key]
                print(f"[get_current_player] Found fallback player_id: {player_id} from key {key}")
                break

    if not player_id:
        print(f"[get_current_player] No player_id found!")
        return None

    try:
        player = PlayerProfile.objects.get(id=player_id)
        print(f"[get_current_player] Returning player: {player.nickname} (id={player.id})")
        return player
    except PlayerProfile.DoesNotExist:
        print(f"[get_current_player] Player not found in DB!")
        return None


def get_tab_id(request):
    """Helper para obter tab_id do request"""
    return request.GET.get('tab') or request.POST.get('tab_id')
