from django.conf import settings
from django.core.urlresolvers import reverse
from django.db.models.query import Q
from django.http import Http404, HttpResponseRedirect
from django.forms.models import inlineformset_factory
from django.shortcuts import get_object_or_404, render_to_response
from django.template import RequestContext
from django.views.generic import list_detail
from django.views.generic import create_update
from ...pypi_config.models import MirrorSite
from ..decorators import user_owns_package, user_maintains_package
from ..models import Package
from ..models import Release
from ..forms import SimplePackageSearchForm
from ..forms import PackageForm

def index(request, **kwargs):
    kwargs.setdefault('template_object_name', 'package')
    kwargs.setdefault('queryset', Package.objects.all())
    return list_detail.object_list(request, **kwargs)

def simple_index(request, **kwargs):
    kwargs.setdefault('template_name', 'pypi_frontend/package_list_simple.html')
    kwargs.setdefault('queryset', Package.objects.all())
    return list_detail.object_list(request, **kwargs)

def _mirror_if_not_found(proxy_folder):
    def decorator(func):
        def internal(request, package, **kwargs):
            try:
                return func(request, package, **kwargs)
            except Http404:
                for mirror_site in MirrorSite.objects.filter(enabled=True):
                    url = '/'.join([mirror_site.url.rstrip('/'), proxy_folder, package])
                    mirror_site.logs.create(action='Redirect to ' + url)
                    return HttpResponseRedirect(url)
            raise Http404(u'%s is not a registered package' % (package,))
        return internal
    return decorator

@_mirror_if_not_found('pypi')
def details(request, package):
    return list_detail.object_detail(
        request,
        object_id            = package,
        template_object_name = 'package',
        queryset             = Package.objects.all(),
    )

@_mirror_if_not_found('simple')
def simple_details(request, package):
    # Find the package
    try:
        obj = Package.objects.get(name__iexact=package)
    except Package.DoesNotExist:
        # If the package is not found, let the mirror handle it
        raise Http404()
    # If the package we found is not exactly the same as the name the user typed, redirect
    # to the proper url:
    if obj.name != package:
        return HttpResponseRedirect(reverse('djangopypi2-package-simple', kwargs=dict(package=obj.name)))
    return render_to_response('pypi_frontend/package_detail_simple.html',
                              context_instance=RequestContext(request, dict(package=obj)),
                              mimetype='text/html')

@_mirror_if_not_found('pypi')
def doap(request, package):
    return list_detail.object_detail(
        request,
        object_id     = package,
        template_name = 'pypi_frontend/package_doap.xml',
        mimetype      = 'text/xml',
        queryset      = Package.objects.all(),
    )

def search(request, **kwargs):
    if request.method == 'POST':
        form = SimplePackageSearchForm(request.POST)
    else:
        form = SimplePackageSearchForm(request.GET)
    
    if form.is_valid():
        q = form.cleaned_data['query']
        kwargs['queryset'] = Package.objects.filter(Q(name__contains=q) | 
                                                    Q(releases__package_info__contains=q)).distinct()
    return index(request, **kwargs)

@user_owns_package()
def manage(request, package, **kwargs):
    kwargs['object_id'] = package
    kwargs.setdefault('form_class', PackageForm)
    kwargs.setdefault('template_name', 'pypi_frontend/package_manage.html')
    kwargs.setdefault('template_object_name', 'package')

    return create_update.update_object(request, **kwargs)

@user_maintains_package()
def manage_versions(request, package, **kwargs):
    package = get_object_or_404(Package, name=package)
    kwargs.setdefault('formset_factory_kwargs', {})
    kwargs['formset_factory_kwargs'].setdefault('fields', ('hidden',))
    kwargs['formset_factory_kwargs']['extra'] = 0

    kwargs.setdefault('formset_factory', inlineformset_factory(Package, Release, **kwargs['formset_factory_kwargs']))
    kwargs.setdefault('template_name', 'pypi_frontend/package_manage_versions.html')
    kwargs.setdefault('template_object_name', 'package')
    kwargs.setdefault('extra_context',{})
    kwargs.setdefault('mimetype',settings.DEFAULT_CONTENT_TYPE)
    kwargs['extra_context'][kwargs['template_object_name']] = package
    kwargs.setdefault('formset_kwargs',{})
    kwargs['formset_kwargs']['instance'] = package

    if request.method == 'POST':
        formset = kwargs['formset_factory'](data=request.POST, **kwargs['formset_kwargs'])
        if formset.is_valid():
            formset.save()
            return create_update.redirect(kwargs.get('post_save_redirect', None),
                                          package)

    formset = kwargs['formset_factory'](**kwargs['formset_kwargs'])

    kwargs['extra_context']['formset'] = formset

    return render_to_response(kwargs['template_name'], kwargs['extra_context'],
                              context_instance=RequestContext(request),
                              mimetype=kwargs['mimetype'])