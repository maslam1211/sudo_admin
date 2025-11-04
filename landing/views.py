from django.shortcuts import render

def index(request):
    return render(request, 'index.html')

def terms(request):
    return render(request, 'terms.html')

def privacy(request):
    return render(request, 'privacy.html')