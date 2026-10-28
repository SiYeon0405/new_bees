from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from users.services import register_user


@ensure_csrf_cookie
@require_http_methods(['GET', 'POST'])
def web_login(request):
    if request.user.is_authenticated:
        return redirect('web-home')
    error = None
    if request.method == 'POST':
        user = authenticate(request, email=request.POST.get('email', ''), password=request.POST.get('password', ''))
        if user is not None:
            login(request, user)
            return redirect('web-home')
        error = '이메일 또는 비밀번호를 확인해 주세요.'
    return render(request, 'web/auth.html', {'mode': 'login', 'error': error})


@ensure_csrf_cookie
@require_http_methods(['GET', 'POST'])
def web_signup(request):
    if request.user.is_authenticated:
        return redirect('web-home')
    error = None
    if request.method == 'POST':
        user, errors = register_user(request.POST.get('email'), request.POST.get('nickname'), request.POST.get('password'))
        if user:
            login(request, user)
            return redirect('web-home')
        error = ' '.join(str(item) for value in errors.values() for item in (value if isinstance(value, list) else [value]))
    return render(request, 'web/auth.html', {'mode': 'signup', 'error': error})


@require_POST
def web_logout(request):
    logout(request)
    return redirect('web-login')


@login_required(login_url='web-login')
@ensure_csrf_cookie
def web_home(request):
    return render(request, 'web/app.html', {'page': 'home'})


@login_required(login_url='web-login')
@ensure_csrf_cookie
def web_group(request, group_id):
    return render(request, 'web/app.html', {'page': 'group', 'group_id': group_id})


@login_required(login_url='web-login')
@ensure_csrf_cookie
def web_file(request, group_id, file_id):
    return render(request, 'web/app.html', {'page': 'file', 'group_id': group_id, 'file_id': file_id})


@login_required(login_url='web-login')
@ensure_csrf_cookie
def web_ask(request, group_id):
    return render(request, 'web/app.html', {'page': 'ask', 'group_id': group_id})
